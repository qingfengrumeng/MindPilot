from app.core.model_preferences import write_preferences
import json

import httpx
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.model_runtime import RuntimeModel
from app.main import create_app
from app.services import rerank_generation


def test_qwen_rerank_uses_native_dashscope_request(monkeypatch):
    observed = {}

    def respond(request):
        observed["url"] = str(request.url)
        observed["authorization"] = request.headers["Authorization"]
        observed["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "output": {"results": [
                {"index": 1, "relevance_score": 0.9},
                {"index": 0, "relevance_score": 0.3},
            ]},
            "usage": {"prompt_tokens": 12, "total_tokens": 12},
        })

    original_client = httpx.Client
    monkeypatch.setattr(rerank_generation.httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(respond), **kwargs
    ))
    config = RuntimeModel(
        "reranker", "dashscope",
        "https://ws-example.cn-beijing.maas.aliyuncs.com/api/v1",
        "qwen3.7-text-rerank", "private-key",
    )
    result = rerank_generation.rerank_texts(config, "什么是向量检索", ["天气晴朗", "向量检索用于语义搜索"], 2)
    assert observed == {
        "url": "https://ws-example.cn-beijing.maas.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
        "authorization": "Bearer private-key",
        "body": {
            "model": "qwen3.7-text-rerank",
            "input": {"query": "什么是向量检索", "documents": ["天气晴朗", "向量检索用于语义搜索"]},
            "parameters": {"top_n": 2},
        },
    }
    assert result["results"][0] == {"index": 1, "relevanceScore": 0.9, "document": "向量检索用于语义搜索"}
    assert result["usage"] == {"totalTokens": 12}


def test_rerank_endpoint_requires_auth_and_local_key(tmp_path, monkeypatch):
    for suffix in ("PROVIDER", "BASE_URL", "API_KEY", "MODEL"):
        monkeypatch.delenv(f"MINDPILOT_RERANKER_{suffix}", raising=False)
    env_path = tmp_path / "models.json"
    write_preferences(env_path, {'providers': {'dashscope': {'name': 'dashscope', 'runtimeProvider': 'dashscope', 'apiKey': '', 'configs': {'reranker': {'baseUrl': 'https://example.com/api/v1', 'model': 'qwen3.7-text-rerank'}}}}, 'active': {'reranker': 'dashscope'}})
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        jwt_secret="test-secret-longer-than-thirty-two-bytes-for-jwt",
        allowed_origins=("http://localhost:5173",),
        model_config_path=env_path,
    )
    payload = {"query": "你好", "documents": ["你好世界"]}
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/v1/rerank", json=payload).status_code == 401
        client.post("/api/v1/auth/register", json={"username": "alice", "password": "strong-password-123"})
        token = client.post("/api/v1/auth/login", json={"username": "alice", "password": "strong-password-123"}).json()["accessToken"]
        response = client.post("/api/v1/rerank", headers={"Authorization": f"Bearer {token}"}, json=payload)
        assert response.status_code == 503
        assert "尚未" in response.json()["detail"]
