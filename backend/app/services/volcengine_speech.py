"""Doubao Speech v3 adapters, using the speech console's shared API Key."""
import asyncio
import base64
import binascii
import gzip
import json
import struct
import zlib
from uuid import uuid4

import httpx
import websocket


class VolcSpeechError(Exception):
    pass


def asr_frame(payload: bytes, *, audio=False, final=False) -> bytes:
    compressed = gzip.compress(payload)
    # Version 1; four-byte header; no client sequence number; gzip payload.
    header = bytes((0x11, (0x20 if audio else 0x10) | (2 if final else 0), 0x01 if audio else 0x11, 0))
    return header + struct.pack(">I", len(compressed)) + compressed


def parse_asr_frame(frame: bytes) -> tuple[str, bool]:
    try:
        if not isinstance(frame, bytes) or len(frame) < 8 or frame[0] >> 4 != 1:
            raise ValueError()
        offset = (frame[0] & 15) * 4
        kind, flags = frame[1] >> 4, frame[1] & 15
        if offset < 4 or offset + 4 > len(frame):
            raise ValueError()
        final = bool(flags & 2)
        if kind == 15:
            raise VolcSpeechError("豆包语音识别请求失败，请检查语音密钥、资源 ID 和服务权限")
        if kind != 9:
            raise ValueError()
        if flags & 1:
            sequence = struct.unpack_from(">i", frame, offset)[0]
            final = final or sequence < 0
            offset += 4
        length = struct.unpack_from(">I", frame, offset)[0]
        payload = frame[offset + 4:]
        if length != len(payload) or length > 2 * 1024 * 1024:
            raise ValueError()
        compression = frame[2] & 15
        if compression == 1:
            decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
            payload = decoder.decompress(payload, 2 * 1024 * 1024 + 1)
            if len(payload) > 2 * 1024 * 1024 or not decoder.eof:
                raise ValueError()
        elif compression != 0:
            raise ValueError()
        if frame[2] >> 4 != 1:
            raise ValueError()
        data = json.loads(payload)
        if data.get("code") not in (None, 0, 1000, 20000000):
            raise VolcSpeechError("豆包语音识别服务返回错误，请检查语音资源配置")
        result = data.get("result") or {}
        if isinstance(result, list):
            result = result[-1] if result else {}
        text = result.get("text", "")
        if not isinstance(text, str):
            raise ValueError()
        return text.strip(), final
    except (ValueError, TypeError, AttributeError, IndexError, struct.error, zlib.error) as exc:
        raise VolcSpeechError("豆包语音识别返回的数据格式不正确") from exc


class VolcAsrSession:
    def __init__(self, config):
        self.connection = None
        try:
            self.connection = websocket.create_connection(config.base_url, timeout=30,
                header=[f"X-Api-Key: {config.api_key}", f"X-Api-Resource-Id: {config.model}",
                        f"X-Api-Request-Id: {uuid4()}", "X-Api-Sequence: -1"])
            payload = {"user": {"uid": "mindpilot"},
                       "audio": {"format": "pcm", "codec": "raw", "rate": 16000, "bits": 16, "channel": 1},
                       "request": {"model_name": "bigmodel", "enable_itn": True, "enable_punc": True,
                                   "show_utterances": False, "result_type": "full"}}
            self.connection.send_binary(asr_frame(json.dumps(payload).encode("utf-8")))
            self.receive()  # Service acknowledgement before recording starts.
        except BaseException:
            self.close()
            raise

    def send_audio(self, pcm, final=False):
        self.connection.send_binary(asr_frame(pcm, audio=True, final=final))

    def receive(self):
        return parse_asr_frame(self.connection.recv())

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None


def transcribe_volc_pcm(config, pcm):
    session = VolcAsrSession(config)
    try:
        session.send_audio(pcm, final=True)
        latest = ""
        while True:
            text, final = session.receive()
            if text:
                latest = text
            if final:
                return latest
    finally:
        session.close()


async def bridge_volc_asr(client, config):
    session = await asyncio.to_thread(VolcAsrSession, config)
    tasks = []
    try:
        await client.send_json({"type": "ready"})
        async def send_audio():
            total = 0
            while True:
                message = await client.receive()
                if message["type"] == "websocket.disconnect":
                    return False
                pcm = message.get("bytes")
                if pcm is not None:
                    total += len(pcm)
                    if not pcm or len(pcm) % 2 or total > 16000 * 2 * 60:
                        raise VolcSpeechError("语音音频格式无效或超过 60 秒")
                    await asyncio.to_thread(session.send_audio, pcm)
                    continue
                try:
                    command = json.loads(message.get("text") or "")
                except (ValueError, TypeError):
                    raise VolcSpeechError("无效的语音控制指令") from None
                if not isinstance(command, dict) or command.get("type") != "stop":
                    raise VolcSpeechError("无效的语音控制指令")
                if total < 3200:
                    raise VolcSpeechError("录音太短，请重试")
                await asyncio.to_thread(session.send_audio, b"", True)
                return True

        async def receive_results():
            latest = ""
            while True:
                text, final = await asyncio.to_thread(session.receive)
                if text:
                    latest = text
                    await client.send_json({"type": "partial", "text": text})
                if final:
                    await client.send_json({"type": "final", "text": latest})
                    await client.send_json({"type": "done"})
                    return

        sender = asyncio.create_task(send_audio())
        receiver = asyncio.create_task(receive_results())
        tasks = [sender, receiver]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if sender in done:
            if sender.result():
                await receiver
        else:
            await receiver
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        # Close the socket to release any outstanding blocking read thread.
        await asyncio.to_thread(session.close)
        await asyncio.gather(*tasks, return_exceptions=True)


def stream_volc_mp3(config, text):
    if not text.strip() or len(text) > 5000:
        raise VolcSpeechError("朗读文本需在 1 至 5000 字之间")
    params = {"text": text, "speaker": config.voice or "zh_female_vv_uranus_bigtts",
              "audio_params": {"format": "mp3", "sample_rate": 24000}}
    total = 0
    try:
        with httpx.Client(timeout=60, follow_redirects=False, trust_env=False) as client:
            with client.stream("POST", config.base_url,
                headers={"X-Api-Key": config.api_key, "X-Api-Resource-Id": config.model,
                         "X-Api-Request-Id": str(uuid4()), "Content-Type": "application/json"},
                json={"user": {"uid": "mindpilot"}, "req_params": params}) as response:
                if response.status_code < 200 or response.status_code >= 300:
                    raise VolcSpeechError(f"豆包语音合成请求失败（HTTP {response.status_code}），请检查语音密钥和资源权限")
                for line in response.iter_lines():
                    if not line.strip() or line.startswith(("event:", ":", "id:")):
                        continue
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if line == "[DONE]":
                        break
                    if len(line) > 30 * 1024 * 1024:
                        raise VolcSpeechError("语音合成结果超过大小限制")
                    event = json.loads(line)
                    if event.get("code") not in (0, 20000000):
                        raise VolcSpeechError("豆包语音合成失败，请检查资源 ID、音色和语音密钥")
                    encoded = event.get("data")
                    if encoded:
                        audio = base64.b64decode(encoded, validate=True)
                        total += len(audio)
                        if total > 20 * 1024 * 1024:
                            raise VolcSpeechError("语音合成结果超过大小限制")
                        yield audio
                    if event.get("code") == 20000000:
                        break
        if not total:
            raise VolcSpeechError("豆包语音合成服务未返回音频")
    except (httpx.HTTPError, ValueError, TypeError, AttributeError, binascii.Error) as exc:
        raise VolcSpeechError("无法连接豆包语音合成服务，或服务返回无效音频") from exc
