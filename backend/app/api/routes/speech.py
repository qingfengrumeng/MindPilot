"""Authenticated speech-to-text API; the vendor API key never reaches the client."""

import base64
import binascii

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import Field

from app.api.deps import CurrentContext
from app.core.model_runtime import require_runtime_model
from app.schemas.base import CamelModel
from app.services.asr_transcription import AsrError, transcribe_pcm
from app.services.tts_synthesis import TtsError, stream_mp3


router = APIRouter(prefix="/speech", tags=["speech"])
GREETING_TEXT = "我是你的智能知识管家思雅，英文名字叫Sarsa，今天你有什么需求吗？随时为你效劳。"


class TranscriptionRequest(CamelModel):
    audio: str = Field(min_length=1, max_length=2_600_000)


class SynthesisRequest(CamelModel):
    text: str = Field(min_length=1, max_length=5000)


@router.post("/transcribe")
def transcribe(payload: TranscriptionRequest, request: Request, _context: CurrentContext):
    try:
        pcm = base64.b64decode(payload.audio, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(422, "音频数据格式不正确") from None
    try:
        config = require_runtime_model("asr", request.app.state.settings.model_config_path)
        text = transcribe_pcm(config, pcm)
        if not text:
            raise HTTPException(422, "未识别到语音，请重试")
        return {"text": text}
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from None
    except AsrError as exc:
        raise HTTPException(502, str(exc)) from None


@router.post("/synthesize")
def synthesize(payload: SynthesisRequest, request: Request, _context: CurrentContext):
    try:
        config = require_runtime_model("tts", request.app.state.settings.model_config_path)
        chunks = stream_mp3(config, payload.text)
        first = next(chunks)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from None
    except TtsError as exc:
        raise HTTPException(502, str(exc)) from None

    def audio_stream():
        try:
            yield first
            yield from chunks
        finally:
            chunks.close()

    return StreamingResponse(audio_stream(), media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


@router.post("/greeting")
def synthesize_greeting(request: Request, _context: CurrentContext):
    """中文开场介绍，使用环境配置中的统一音色。"""
    try:
        config = require_runtime_model("tts", request.app.state.settings.model_config_path)
        chunks = stream_mp3(config, GREETING_TEXT)
        first = next(chunks)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from None
    except TtsError as exc:
        raise HTTPException(502, str(exc)) from None

    def audio_stream():
        try:
            yield first
            yield from chunks
        finally:
            chunks.close()

    return StreamingResponse(audio_stream(), media_type="audio/mpeg", headers={"Cache-Control": "private, no-store"})
