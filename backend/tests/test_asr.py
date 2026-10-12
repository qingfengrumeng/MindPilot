from app.core.model_preferences import write_preferences
import base64
import json
from queue import Queue

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.model_runtime import RuntimeModel
from app.main import create_app
from app.api.routes import speech_live
from app.services import asr_transcription


def test_qwen_realtime_manual_protocol(monkeypatch):
    sent = []
    observed = {}
    replies = iter([
        {"type": "session.created"},
        {"type": "session.updated"},
        {"type": "input_audio_buffer.committed"},
        {"type": "conversation.item.input_audio_transcription.completed", "transcript": "你好，世界"},
        {"type": "session.finished"},
    ])

    class FakeConnection:
        def send(self, payload):
            sent.append(json.loads(payload))

        def recv(self):
            return json.dumps(next(replies))

        def close(self):
            observed["closed"] = True

    def connect(url, header, timeout):
        observed.update(url=url, header=header, timeout=timeout)
        return FakeConnection()

    monkeypatch.setattr(asr_transcription.websocket, "create_connection", connect)
    monkeypatch.setattr(asr_transcription.time, "sleep", lambda _: None)
    config = RuntimeModel(
        "asr", "dashscope", "wss://ws-example.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime",
        "qwen3-asr-flash-realtime", "private-key",
    )
    pcm = b"\x01\x00" * 1600
    assert asr_transcription.transcribe_pcm(config, pcm) == "你好，世界"
    assert observed["url"].endswith("?model=qwen3-asr-flash-realtime")
    assert "Authorization: Bearer private-key" in observed["header"]
    assert observed["closed"]
    assert [item["type"] for item in sent] == [
        "session.update", "input_audio_buffer.append", "input_audio_buffer.commit", "session.finish",
    ]
    assert sent[0]["session"]["turn_detection"] is None
    assert base64.b64decode(sent[1]["audio"]) == pcm


def test_live_asr_rejects_missing_login(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        jwt_secret="test-secret-longer-than-thirty-two-bytes-for-jwt",
        allowed_origins=("http://localhost:5173",),
        model_config_path=tmp_path / "models.json",
    )
    with TestClient(create_app(settings)) as client:
        with client.websocket_connect("/api/v1/speech/live", headers={"origin": "http://localhost:5173"}) as socket:
            socket.send_json({"type": "start", "token": ""})
            assert socket.receive_json() == {"type": "error", "message": "请先登录后再使用语音识别"}


def test_live_asr_streams_microphone_and_partial_text(tmp_path, monkeypatch):
    for suffix in ("PROVIDER", "BASE_URL", "API_KEY", "MODEL"):
        monkeypatch.delenv(f"MINDPILOT_ASR_{suffix}", raising=False)
    env_path = tmp_path / "models.json"
    write_preferences(env_path, {'providers': {'dashscope': {'name': 'dashscope', 'runtimeProvider': 'dashscope', 'apiKey': 'private-key', 'configs': {'asr': {'baseUrl': 'wss://example.com/api-ws/v1/realtime', 'model': 'qwen3-asr-flash-realtime'}}}}, 'active': {'asr': 'dashscope'}})
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        jwt_secret="test-secret-longer-than-thirty-two-bytes-for-jwt",
        allowed_origins=("http://localhost:5173",),
        model_config_path=env_path,
    )
    sent = []

    class FakeConnection:
        def __init__(self):
            self.events = Queue()
            self.events.put({"type": "session.created"})
            self.events.put({"type": "session.updated"})

        def send(self, payload):
            event = json.loads(payload)
            sent.append(event)
            if event["type"] == "input_audio_buffer.append":
                self.events.put({"type": "conversation.item.input_audio_transcription.text", "text": "你", "stash": "好"})
            if event["type"] == "input_audio_buffer.commit":
                self.events.put({"type": "conversation.item.input_audio_transcription.completed", "transcript": "你好"})
            if event["type"] == "session.finish":
                self.events.put({"type": "session.finished"})

        def recv(self):
            return json.dumps(self.events.get(timeout=3))

        def close(self):
            pass

    monkeypatch.setattr(speech_live.websocket_client, "create_connection", lambda *args, **kwargs: FakeConnection())
    with TestClient(create_app(settings)) as client:
        client.post("/api/v1/auth/register", json={"username": "alice", "password": "strong-password-123"})
        token = client.post("/api/v1/auth/login", json={"username": "alice", "password": "strong-password-123"}).json()["accessToken"]
        with client.websocket_connect("/api/v1/speech/live", headers={"origin": "http://localhost:5173"}) as socket:
            socket.send_json({"type": "start", "token": token})
            assert socket.receive_json() == {"type": "ready"}
            socket.send_bytes(b"\x01\x00" * 1600)
            assert socket.receive_json() == {"type": "partial", "text": "你好"}
            socket.send_json({"type": "stop"})
            assert socket.receive_json() == {"type": "final", "text": "你好"}
            assert socket.receive_json() == {"type": "done"}
    assert [event["type"] for event in sent] == [
        "session.update", "input_audio_buffer.append", "input_audio_buffer.commit", "session.finish",
    ]
