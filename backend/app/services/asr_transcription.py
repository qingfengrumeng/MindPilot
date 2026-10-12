"""Qwen3-ASR-Flash-Realtime manual-mode transcription over WebSocket."""

import base64
import json
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import websocket

from app.core.model_runtime import RuntimeModel


class AsrError(Exception):
    pass


def _event(kind: str, **fields) -> str:
    return json.dumps({"event_id": f"event_{uuid4().hex}", "type": kind, **fields})


def _url(config: RuntimeModel) -> str:
    parts = urlsplit(config.base_url)
    if parts.scheme != "wss" or not parts.hostname:
        raise AsrError("ASR 接口地址必须是有效的 wss:// 地址")
    query = dict(parse_qsl(parts.query))
    query["model"] = config.model
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def transcribe_pcm(config: RuntimeModel, pcm: bytes) -> str:
    if config.provider == "volcengine":
        if not 3200 <= len(pcm) <= 16000 * 2 * 60 or len(pcm) % 2:
            raise AsrError("请提供 0.1 至 60 秒的 16 kHz 单声道 PCM16 音频")
        from app.services.volcengine_speech import VolcSpeechError, transcribe_volc_pcm
        try:
            return transcribe_volc_pcm(config, pcm)
        except (VolcSpeechError, websocket.WebSocketException, OSError, TimeoutError) as exc:
            raise AsrError("豆包语音识别失败，请检查语音模型配置与网络") from exc
    if config.provider != "dashscope" or config.model != "qwen3-asr-flash-realtime":
        raise AsrError("当前仅支持百炼 qwen3-asr-flash-realtime 语音识别模型")
    if not 3200 <= len(pcm) <= 16000 * 2 * 60 or len(pcm) % 2:
        raise AsrError("请提供 0.1 至 60 秒的 16 kHz 单声道 PCM16 音频")

    try:
        connection = websocket.create_connection(
            _url(config),
            header=[f"Authorization: Bearer {config.api_key}", "OpenAI-Beta: realtime=v1"],
            timeout=30,
        )
        try:
            connection.send(_event("session.update", session={
                "modalities": ["text"], "input_audio_format": "pcm", "sample_rate": 16000,
                "turn_detection": None,
            }))
            # Wait for the configuration acknowledgement before sending audio.
            while True:
                response = json.loads(connection.recv())
                if response.get("type") == "error":
                    raise AsrError("语音识别服务未接受会话配置，请检查 ASR 配置")
                if response.get("type") == "session.updated":
                    break

            for start in range(0, len(pcm), 3200):
                chunk = pcm[start:start + 3200]
                connection.send(_event("input_audio_buffer.append", audio=base64.b64encode(chunk).decode("ascii")))
                time.sleep(len(chunk) / 32000)
            connection.send(_event("input_audio_buffer.commit"))
            connection.send(_event("session.finish"))

            transcripts = []
            while True:
                response = json.loads(connection.recv())
                kind = response.get("type")
                if kind == "error":
                    raise AsrError("语音识别服务处理失败，请检查音频或稍后重试")
                if kind == "conversation.item.input_audio_transcription.failed":
                    raise AsrError("语音识别失败，请重试或检查音频格式")
                if kind == "conversation.item.input_audio_transcription.completed":
                    transcript = response.get("transcript", "").strip()
                    if transcript:
                        transcripts.append(transcript)
                if kind == "session.finished":
                    return "".join(transcripts)
        finally:
            connection.close()
    except (websocket.WebSocketException, OSError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        raise AsrError("无法连接语音识别服务，或等待识别结果超时") from exc
