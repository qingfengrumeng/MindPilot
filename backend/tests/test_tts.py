from app.core.model_preferences import write_preferences
import json

import pytest
import websocket
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.model_runtime import RuntimeModel
from app.main import create_app
from app.api.routes import speech
from app.services import tts_synthesis


@pytest.mark.parametrize("spoken_text, language", [
    ("Hello there.", "en"),
    ("你好", "zh"),
])
def test_qwen_tts_inference_stream(monkeypatch, spoken_text, language):
    observed = {}
    sent = []
    frames = iter([
        (websocket.ABNF.OPCODE_TEXT, json.dumps({"header": {"event": "task-started"}})),
        (websocket.ABNF.OPCODE_TEXT, json.dumps({"header": {"event": "result-generated"}})),
        (websocket.ABNF.OPCODE_BINARY, b"first-mp3-frame"),
        (websocket.ABNF.OPCODE_BINARY, b"second-mp3-frame"),
        (websocket.ABNF.OPCODE_TEXT, json.dumps({"header": {"event": "task-finished"}})),
    ])

    class FakeConnection:
        def send(self, data):
            sent.append(json.loads(data))

        def recv_data(self):
            return next(frames)

        def close(self):
            observed["closed"] = True

    def connect(url, header, timeout):
        observed.update(url=url, header=header, timeout=timeout)
        return FakeConnection()

    monkeypatch.setattr(tts_synthesis.websocket, "create_connection", connect)
    config = RuntimeModel(
        "tts", "dashscope", "wss://ws-example.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference",
        "qwen-audio-3.1-tts-flash", "private-key", voice="longanwen_v3.1",
        instruction="Speak in a precise synthetic style.",
    )
    assert list(tts_synthesis.stream_mp3(config, spoken_text)) == [b"first-mp3-frame", b"second-mp3-frame"]
    assert observed["url"].endswith("/api-ws/v1/inference")
    assert "Authorization: Bearer private-key" in observed["header"]
    assert observed["closed"]
    assert [command["header"]["action"] for command in sent] == ["run-task", "continue-task", "finish-task"]
    assert len({command["header"]["task_id"] for command in sent}) == 1
    parameters = sent[0]["payload"]["parameters"]
    assert parameters["voice"] == "longanwen_v3.1"
    assert parameters["instruction"] == "Speak in a precise synthetic style."
    assert parameters["language_hints"] == [language]
    assert sent[1]["payload"]["input"]["text"] == spoken_text


def test_tts_endpoint_requires_login_and_streams_mp3(tmp_path, monkeypatch):
    for suffix in ("PROVIDER", "BASE_URL", "API_KEY", "MODEL", "VOICE", "INSTRUCTION"):
        monkeypatch.delenv(f"MINDPILOT_TTS_{suffix}", raising=False)
    for suffix in ("PROVIDER", "BASE_URL", "API_KEY", "MODEL"):
        monkeypatch.delenv(f"MINDPILOT_TEXT_{suffix}", raising=False)
    env_path = tmp_path / "models.json"
    write_preferences(env_path, {'providers': {'deepseek': {'name': 'deepseek', 'runtimeProvider': 'deepseek', 'apiKey': 'private-key', 'configs': {'text': {'baseUrl': 'https://api.deepseek.com', 'model': 'deepseek-flash'}}}, 'dashscope': {'name': 'dashscope', 'runtimeProvider': 'dashscope', 'apiKey': 'private-key', 'configs': {'tts': {'baseUrl': 'wss://example.com/api-ws/v1/inference', 'model': 'qwen-audio-3.1-tts-flash', 'voice': 'longanwen_v3.1', 'instruction': None}}}}, 'active': {'text': 'deepseek', 'tts': 'dashscope'}})
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        jwt_secret="test-secret-longer-than-thirty-two-bytes-for-jwt",
        allowed_origins=("http://localhost:5173",),
        model_config_path=env_path,
    )
    observed = {}

    def fake_stream(config, text):
        observed["model"] = config.model
        observed["voice"] = config.voice
        observed["text"] = text
        yield b"first"
        yield b"second"

    monkeypatch.setattr(speech, "stream_mp3", fake_stream)
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/v1/speech/synthesize", json={"text": "你好"}).status_code == 401
        assert client.post("/api/v1/speech/greeting").status_code == 401
        client.post("/api/v1/auth/register", json={"username": "alice", "password": "strong-password-123"})
        token = client.post("/api/v1/auth/login", json={"username": "alice", "password": "strong-password-123"}).json()["accessToken"]
        response = client.post(
            "/api/v1/speech/synthesize", json={"text": "你好"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/mpeg"
        assert response.content == b"firstsecond"
        assert observed == {"model": "qwen-audio-3.1-tts-flash", "voice": "longanwen_v3.1", "text": "你好"}
        greeting = client.post("/api/v1/speech/greeting", headers={"Authorization": f"Bearer {token}"})
        assert greeting.status_code == 200
        assert greeting.headers["content-type"] == "audio/mpeg"
        assert greeting.content == b"firstsecond"
    assert observed == {"model": "qwen-audio-3.1-tts-flash", "voice": "longanwen_v3.1", "text": "我是你的智能知识管家思雅，英文名字叫Sarsa，今天你有什么需求吗？随时为你效劳。"}
