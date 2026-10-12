from app.core.model_preferences import write_preferences
import json

import httpx
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.model_runtime import RuntimeModel
from app.main import create_app
from app.services import embedding_generation


def test_qwen_embedding_request_matches_documented_api(monkeypatch):
    observed = {}

    def respond(request):
        observed["url"] = str(request.url)
        observed["authorization"] = request.headers["Authorization"]
        observed["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "data": [
                {"index": 1, "embedding": [0.2] * 1024},
                {"index": 0, "embedding": [0.1] * 1024},
            ],
            "usage": {"total_tokens": 6},
        })

    original_client = httpx.Client
    monkeypatch.setattr(embedding_generation.httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(respond), **kwargs
    ))
    config = RuntimeModel(
        "embedding", "dashscope",
        "https://ws-example.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "qwen3.7-text-embedding", "private-key", 1024,
    )
    result = embedding_generation.embed_texts(config, ["第一段", "第二段"])
    assert observed == {
        "url": "https://ws-example.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/embeddings",
        "authorization": "Bearer private-key",
        "body": {
            "model": "qwen3.7-text-embedding",
            "input": ["第一段", "第二段"],
            "dimensions": 1024,
            "encoding_format": "float",
        },
    }
    assert [item["index"] for item in result["data"]] == [0, 1]
    assert len(result["data"][0]["embedding"]) == 1024
    assert result["usage"] == {"totalTokens": 6}


def test_embedding_endpoint_requires_auth_and_local_key(tmp_path, monkeypatch):
    for suffix in ("PROVIDER", "BASE_URL", "API_KEY", "MODEL", "DIMENSIONS"):
        monkeypatch.delenv(f"MINDPILOT_EMBEDDING_{suffix}", raising=False)
    env_path = tmp_path / "models.json"
    write_preferences(env_path, {'providers': {'dashscope': {'name': 'dashscope', 'runtimeProvider': 'dashscope', 'apiKey': '', 'configs': {'embedding': {'baseUrl': 'https://example.com/compatible-mode/v1', 'model': 'qwen3.7-text-embedding', 'dimensions': 1024}}}}, 'active': {'embedding': 'dashscope'}})
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        jwt_secret="test-secret-longer-than-thirty-two-bytes-for-jwt",
        allowed_origins=("http://localhost:5173",),
        model_config_path=env_path,
    )
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/v1/embeddings", json={"input": "你好"}).status_code == 401
        client.post("/api/v1/auth/register", json={"username": "alice", "password": "strong-password-123"})
        token = client.post("/api/v1/auth/login", json={"username": "alice", "password": "strong-password-123"}).json()["accessToken"]
        response = client.post("/api/v1/embeddings", headers={"Authorization": f"Bearer {token}"}, json={"input": "你好"})
        assert response.status_code == 503
        assert "尚未" in response.json()["detail"]
