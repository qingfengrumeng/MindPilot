from app.core.model_preferences import write_preferences
import base64
import gzip
import json
import struct
import threading
import time

import httpx
import pytest
import websocket
from fastapi.testclient import TestClient

from app.core.model_runtime import RuntimeModel, require_runtime_model
from app.main import create_app
from app.services import embedding_generation, volcengine_speech
from app.services.asr_transcription import transcribe_pcm
from app.services.tts_synthesis import TtsError, stream_mp3
from tests.test_model_configs import login, settings_for


def test_volcengine_catalog_shared_credential_groups_and_runtime(tmp_path):
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings)) as client:
        headers = login(client)
        catalogue = client.get("/api/v1/model-configs", headers=headers).json()
        providers = {p["id"]: p for p in catalogue["providers"]}
        assert {"volcengine", "zhipu", "custom"} <= providers.keys()
        volc = providers["volcengine"]
        assert set(volc["defaults"]) == {"text", "embedding", "asr", "tts"}
        payload = {"name": "豆包", "apiKey": "ark-private", "speechApiKey": "speech-private", "configs": volc["defaults"]}
        response = client.put("/api/v1/model-configs/volcengine", headers=headers, json=payload)
        assert response.status_code == 200
        assert "ark-private" not in response.text and "speech-private" not in response.text
        for category in volc["defaults"]:
            assert client.put(f"/api/v1/model-configs/active/{category}", headers=headers, json={"providerId": "volcengine"}).status_code == 200
            runtime = require_runtime_model(category, settings.model_config_path)
            assert runtime.provider == "volcengine"
            assert runtime.api_key == ("speech-private" if category in {"asr", "tts"} else "ark-private")
        assert require_runtime_model("embedding", settings.model_config_path).embedding_protocol == "multimodal"
        client.put("/api/v1/model-configs/volcengine", headers=headers, json={"name": "豆包", "speechApiKey": "speech-rotated"})
        assert require_runtime_model("tts", settings.model_config_path).api_key == "speech-rotated"
        assert require_runtime_model("text", settings.model_config_path).api_key == "ark-private"
        response = client.put("/api/v1/model-configs/volcengine", headers=headers, json={"name": "豆包", "clearSpeechApiKey": True})
        assert response.json()["active"]["asr"] is None and response.json()["active"]["tts"] is None
        assert require_runtime_model("text", settings.model_config_path).configured
        assert require_runtime_model("embedding", settings.model_config_path).configured
        # The built-in custom slot accepts real compatible embeddings too.
        response = client.put("/api/v1/model-configs/custom", headers=headers, json={"name": "自定义接口", "apiKey": "local-key",
            "configs": {"embedding": {"baseUrl": "http://localhost:1234/v1", "model": "local-embed", "dimensions": 384}}})
        assert response.status_code == 200
        assert client.put("/api/v1/model-configs/active/embedding", headers=headers, json={"providerId": "custom"}).status_code == 200
        assert require_runtime_model("embedding", settings.model_config_path).provider == "openai"


@pytest.mark.parametrize('model', ['doubao-embedding-vision-251215', 'doubao-embedding-vision-250615'])
def test_ark_multimodal_embeddings_keep_one_vector_per_document(monkeypatch, model):
    observed = []
    def respond(request):
        payload = json.loads(request.content)
        observed.append(payload)
        assert str(request.url).endswith("/embeddings/multimodal")
        assert request.headers["Authorization"] == "Bearer ark-key"
        return httpx.Response(200, json={"data": {"embedding": [len(observed) / 10] * 1024}, "usage": {"total_tokens": 3}})
    original = httpx.Client
    monkeypatch.setattr(embedding_generation.httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    config = RuntimeModel("embedding", "volcengine", "https://ark.example/api/v3", model, "ark-key", 1024,
                          instruction="Represent text for retrieval", embedding_protocol="multimodal")
    result = embedding_generation.embed_texts(config, ["first document", "second document"])
    assert [p["input"] for p in observed] == [[{"type": "text", "text": "first document"}], [{"type": "text", "text": "second document"}]]
    assert observed[0].get("instructions") == (config.instruction if model.endswith('251215') else None)
    assert [row["embedding"][0] for row in result["data"]] == [0.1, 0.2]
    assert result["usage"]["totalTokens"] == 6


def test_custom_compatible_embeddings_use_batched_protocol(monkeypatch):
    def respond(request):
        body = json.loads(request.content)
        assert body["input"] == ["first", "second"] and str(request.url).endswith("/embeddings")
        return httpx.Response(200, json={"data": [{"index": 1, "embedding": [0.2] * 3}, {"index": 0, "embedding": [0.1] * 3}]})
    original = httpx.Client
    monkeypatch.setattr(embedding_generation.httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    result = embedding_generation.embed_texts(RuntimeModel("embedding", "openai", "http://localhost/v1", "local", "key", 3), ["first", "second"])
    assert [r["index"] for r in result["data"]] == [0, 1]


def server_frame(text="", final=False):
    payload = gzip.compress(json.dumps({"result": {"text": text}}).encode())
    return bytes([0x11, 0x93 if final else 0x91, 0x11, 0]) + struct.pack(">iI", -3 if final else 1, len(payload)) + payload


class FakeAsrSocket:
    def __init__(self):
        self.frames = []
        self.queue = []
        self.condition = threading.Condition()
        self.closed = False
    def send_binary(self, data):
        self.frames.append(data)
        with self.condition:
            kind, final = data[1] >> 4, bool(data[1] & 2)
            self.queue.append(server_frame("" if kind == 1 else "你好世界" if final else "你好", final))
            self.condition.notify_all()
    def recv(self):
        with self.condition:
            deadline = time.monotonic() + 5
            while not self.queue:
                if self.closed or time.monotonic() > deadline:
                    raise websocket.WebSocketConnectionClosedException()
                self.condition.wait(.1)
            return self.queue.pop(0)
    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()


def test_volc_asr_binary_protocol_and_final_transcript(monkeypatch):
    socket = FakeAsrSocket()
    def connect(url, header, timeout):
        assert url.endswith("/sauc/bigmodel_async")
        assert "X-Api-Key: speech-key" in header
        assert "X-Api-Resource-Id: volc.seedasr.sauc.duration" in header
        return socket
    monkeypatch.setattr(volcengine_speech.websocket, "create_connection", connect)
    config = RuntimeModel("asr", "volcengine", "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async", "volc.seedasr.sauc.duration", "speech-key")
    pcm = b"\x00\x01" * 1600
    assert transcribe_pcm(config, pcm) == "你好世界"
    first = json.loads(gzip.decompress(socket.frames[0][8:]))
    assert first["audio"]["rate"] == 16000 and first["audio"]["format"] == "pcm"
    assert gzip.decompress(socket.frames[1][8:]) == pcm and socket.frames[1][1] == 0x22
    assert socket.closed
    with pytest.raises(volcengine_speech.VolcSpeechError):
        volcengine_speech.parse_asr_frame(b"invalid")


def test_volc_live_bridge_uses_existing_browser_events(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    write_preferences(settings.model_config_path, {'providers': {'volcengine': {'name': 'volcengine', 'runtimeProvider': 'volcengine', 'apiKey': 'speech-key', 'configs': {'asr': {'baseUrl': 'wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async', 'model': 'volc.seedasr.sauc.duration'}}, 'speechApiKey': 'speech-key'}}, 'active': {'asr': 'volcengine'}})
    socket = FakeAsrSocket()
    monkeypatch.setattr(volcengine_speech.websocket, "create_connection", lambda *args, **kwargs: socket)
    with TestClient(create_app(settings)) as client:
        headers = login(client)
        with client.websocket_connect("/api/v1/speech/live") as connection:
            connection.send_json({"type": "start", "token": headers["Authorization"][7:]})
            assert connection.receive_json() == {"type": "ready"}
            connection.send_bytes(b"\x00\x01" * 1600)
            assert connection.receive_json() == {"type": "partial", "text": "你好"}
            connection.send_json({"type": "stop"})
            assert connection.receive_json() == {"type": "partial", "text": "你好世界"}
            assert connection.receive_json() == {"type": "final", "text": "你好世界"}
            assert connection.receive_json() == {"type": "done"}
    assert socket.closed


def test_volc_tts_stream_decodes_audio_and_checks_resource_errors(monkeypatch):
    observed = {}
    def respond(request):
        observed["body"] = json.loads(request.content)
        assert request.headers["X-Api-Key"] == "speech-key" and request.headers["X-Api-Resource-Id"] == "seed-tts-2.0"
        return httpx.Response(200, text='\n'.join([json.dumps({"code": 0, "data": base64.b64encode(b"mp3-first").decode()}),
            json.dumps({"code": 0, "data": base64.b64encode(b"mp3-second").decode()}), json.dumps({"code": 20000000})]))
    original = httpx.Client
    monkeypatch.setattr(volcengine_speech.httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    config = RuntimeModel("tts", "volcengine", "https://openspeech.bytedance.com/api/v3/tts/unidirectional", "seed-tts-2.0", "speech-key", voice="zh_female_vv_uranus_bigtts")
    assert b"".join(stream_mp3(config, "你好")) == b"mp3-firstmp3-second"
    assert observed["body"]["req_params"]["audio_params"]["format"] == "mp3"
    assert observed["body"]["req_params"]["speaker"] == config.voice
    monkeypatch.setattr(volcengine_speech.httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"code": 55000000, "message": "private-upstream-detail"})), **kwargs))
    with pytest.raises(TtsError, match="音色"):
        list(stream_mp3(config, "你好"))
