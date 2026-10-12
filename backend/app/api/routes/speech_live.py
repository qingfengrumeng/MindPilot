"""Authenticated browser-to-provider realtime ASR bridge."""

import asyncio
import base64
import json
from uuid import uuid4

import jwt
import websocket as websocket_client
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.model_runtime import require_runtime_model
from app.core.security import decode_access_token, is_expired
from app.db.models import AuthSession, User
from app.services.asr_transcription import AsrError, _url
from app.services.volcengine_speech import VolcSpeechError, bridge_volc_asr


router = APIRouter(prefix="/speech", tags=["speech"])


def _event(kind: str, **fields) -> str:
    return json.dumps({"event_id": f"event_{uuid4().hex}", "type": kind, **fields})


async def _error(client: WebSocket, message: str):
    try:
        await client.send_json({"type": "error", "message": message})
    except (RuntimeError, WebSocketDisconnect):
        pass


@router.websocket("/live")
async def live_transcribe(client: WebSocket):
    settings = client.app.state.settings
    origin = client.headers.get("origin")
    if origin and origin not in settings.allowed_origins:
        await client.close(code=1008)
        return
    await client.accept()
    upstream = None
    try:
        try:
            start = await asyncio.wait_for(client.receive_json(), timeout=8)
        except (ValueError, asyncio.TimeoutError):
            raise AsrError("语音识别连接请求无效") from None
        token = start.get("token", "") if isinstance(start, dict) and start.get("type") == "start" else ""
        if not isinstance(token, str) or not token or len(token) > 4096:
            raise AsrError("请先登录后再使用语音识别")
        try:
            claims = decode_access_token(token, settings)
        except (jwt.PyJWTError, KeyError):
            raise AsrError("登录已过期，请重新登录") from None
        with client.app.state.session_factory() as db:
            session = db.get(AuthSession, claims["sid"])
            user = db.get(User, claims["sub"])
            if not session or not user or session.user_id != user.id or session.revoked_at or is_expired(session.expires_at):
                raise AsrError("登录已过期，请重新登录")
        config = require_runtime_model("asr", settings.model_config_path)
        if config.provider == "volcengine":
            await bridge_volc_asr(client, config)
            return
        if config.provider != "dashscope" or config.model != "qwen3-asr-flash-realtime":
            raise AsrError("当前仅支持百炼 qwen3-asr-flash-realtime 语音识别模型")
        upstream = await asyncio.to_thread(
            websocket_client.create_connection, _url(config),
            header=[f"Authorization: Bearer {config.api_key}", "OpenAI-Beta: realtime=v1"],
            timeout=10,
        )
        await asyncio.to_thread(upstream.send, _event("session.update", session={
            "modalities": ["text"], "input_audio_format": "pcm", "sample_rate": 16000,
            "turn_detection": None,
        }))
        while True:
            event = json.loads(await asyncio.to_thread(upstream.recv))
            if event.get("type") == "error":
                raise AsrError("语音识别服务未接受会话配置，请检查 ASR 配置")
            if event.get("type") == "session.updated":
                break
        await client.send_json({"type": "ready"})

        async def send_audio() -> bool:
            total_bytes = 0
            while True:
                message = await client.receive()
                if message["type"] == "websocket.disconnect":
                    return False
                chunk = message.get("bytes")
                if chunk is not None:
                    total_bytes += len(chunk)
                    if not chunk or len(chunk) % 2 or total_bytes > 16000 * 2 * 60:
                        raise AsrError("语音音频格式无效或超过 60 秒")
                    await asyncio.to_thread(upstream.send, _event(
                        "input_audio_buffer.append", audio=base64.b64encode(chunk).decode("ascii"),
                    ))
                    continue
                raw_command = message.get("text")
                if not isinstance(raw_command, str):
                    raise AsrError("无效的语音控制指令")
                try:
                    command = json.loads(raw_command)
                except ValueError:
                    raise AsrError("无效的语音控制指令") from None
                if not isinstance(command, dict) or command.get("type") != "stop":
                    raise AsrError("无效的语音控制指令")
                if total_bytes < 3200:
                    raise AsrError("录音太短，请重试")
                await asyncio.to_thread(upstream.send, _event("input_audio_buffer.commit"))
                await asyncio.to_thread(upstream.send, _event("session.finish"))
                return True

        async def receive_results():
            while True:
                event = json.loads(await asyncio.to_thread(upstream.recv))
                kind = event.get("type")
                if kind in {"error", "conversation.item.input_audio_transcription.failed"}:
                    raise AsrError("语音识别失败，请重试")
                if kind == "conversation.item.input_audio_transcription.text":
                    await client.send_json({"type": "partial", "text": event.get("text", "") + event.get("stash", "")})
                elif kind == "conversation.item.input_audio_transcription.completed":
                    await client.send_json({"type": "final", "text": event.get("transcript", "")})
                elif kind == "session.finished":
                    await client.send_json({"type": "done"})
                    return

        sender = asyncio.create_task(send_audio())
        receiver = asyncio.create_task(receive_results())
        try:
            done, _ = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
            if sender in done:
                if sender.result():
                    await receiver
                else:
                    receiver.cancel()
            else:
                await receiver
                sender.cancel()
        finally:
            for task in (sender, receiver):
                if not task.done():
                    task.cancel()
    except WebSocketDisconnect:
        pass
    except (AsrError, VolcSpeechError, RuntimeError) as exc:
        await _error(client, str(exc))
    except (websocket_client.WebSocketException, OSError, TimeoutError, ValueError, KeyError):
        await _error(client, "无法连接语音识别服务，或等待识别结果超时")
    finally:
        if upstream:
            await asyncio.to_thread(upstream.close)
        try:
            await client.close()
        except RuntimeError:
            pass
