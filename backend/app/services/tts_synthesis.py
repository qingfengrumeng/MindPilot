"""Stream Qwen-Audio-3.1-TTS-Flash MP3 frames from the inference WebSocket."""

import json
import re
from collections.abc import Iterator
from urllib.parse import urlsplit
from uuid import uuid4

import websocket

from app.core.model_runtime import RuntimeModel


class TtsError(Exception):
    pass


def _command(action: str, task_id: str, payload: dict) -> str:
    return json.dumps({
        "header": {"action": action, "task_id": task_id, "streaming": "duplex"},
        "payload": payload,
    }, ensure_ascii=False)


def _receive_event(connection) -> dict | bytes:
    opcode, data = connection.recv_data()
    if opcode == websocket.ABNF.OPCODE_BINARY:
        return data
    if opcode != websocket.ABNF.OPCODE_TEXT:
        raise TtsError("语音合成连接意外中断")
    try:
        return json.loads(data)
    except (TypeError, ValueError) as exc:
        raise TtsError("语音合成服务返回无效数据") from exc


def stream_mp3(config: RuntimeModel, text: str) -> Iterator[bytes]:
    if config.provider == "volcengine":
        from app.services.volcengine_speech import VolcSpeechError, stream_volc_mp3
        try:
            yield from stream_volc_mp3(config, text)
            return
        except VolcSpeechError as exc:
            raise TtsError(str(exc)) from exc
    if config.provider != "dashscope" or config.model != "qwen-audio-3.1-tts-flash":
        raise TtsError("当前仅支持百炼 qwen-audio-3.1-tts-flash 语音合成模型")
    parts = urlsplit(config.base_url)
    if parts.scheme != "wss" or not parts.hostname or parts.path != "/api-ws/v1/inference":
        raise TtsError("TTS 接口地址必须是 /api-ws/v1/inference 的 wss:// 地址")
    if not text.strip() or len(text) > 5000:
        raise TtsError("朗读文本需在 1 至 5000 字之间")

    is_chinese = bool(re.search(r"[\u3400-\u9fff]", text))
    selected_voice = config.voice or "longanwen_v3.1"
    parameters = {
        "text_type": "PlainText", "voice": selected_voice,
        "format": "mp3", "sample_rate": 22050, "rate": 0.88,
        "language_hints": ["zh" if is_chinese else "en"],
    }
    if config.instruction:
        parameters["instruction"] = config.instruction

    task_id = str(uuid4())
    try:
        connection = websocket.create_connection(
            config.base_url,
            header=[f"Authorization: Bearer {config.api_key}", "X-DashScope-DataInspection: enable"],
            timeout=30,
        )
        try:
            connection.send(_command("run-task", task_id, {
                "task_group": "audio", "task": "tts", "function": "SpeechSynthesizer",
                "model": config.model,
                "parameters": parameters,
                "input": {},
            }))
            while True:
                event = _receive_event(connection)
                if isinstance(event, dict):
                    kind = event.get("header", {}).get("event")
                    if kind == "task-failed":
                        raise TtsError("语音合成任务启动失败，请检查模型、音色和 API Key")
                    if kind == "task-started":
                        break
            connection.send(_command("continue-task", task_id, {"input": {"text": text}}))
            connection.send(_command("finish-task", task_id, {"input": {}}))
            total_bytes = 0
            while True:
                event = _receive_event(connection)
                if isinstance(event, bytes):
                    total_bytes += len(event)
                    if total_bytes > 20 * 1024 * 1024:
                        raise TtsError("语音合成结果超过大小限制")
                    if event:
                        yield event
                    continue
                kind = event.get("header", {}).get("event")
                if kind == "task-failed":
                    raise TtsError("语音合成失败，请稍后重试")
                if kind == "task-finished":
                    if not total_bytes:
                        raise TtsError("语音合成服务未返回音频")
                    return
        finally:
            connection.close()
    except (websocket.WebSocketException, OSError, TimeoutError) as exc:
        raise TtsError("无法连接语音合成服务，或等待音频超时") from exc
