from app.core.model_preferences import write_preferences
import base64
import json

import httpx
from fastapi.testclient import TestClient
import pytest

from app.api.routes import images
from app.core.config import Settings
from app.core.model_runtime import RuntimeModel
from app.main import create_app
from app.services import image_generation


def test_qwen_image_uses_compatible_images_api(monkeypatch):
    observed = {}

    def respond(request):
        observed["url"] = str(request.url)
        observed["authorization"] = request.headers["Authorization"]
        observed["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "data": [{"url": "https://dashscope-result.oss-cn-beijing.aliyuncs.com/result.png"}],
            "usage": {"output_width": 1024, "output_height": 1536},
        })

    original_client = httpx.Client
    monkeypatch.setattr(image_generation.httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(respond), **kwargs
    ))
    config = RuntimeModel(
        "image", "dashscope",
        "https://ws-example.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "qwen-image-3.0-pro", "private-key",
    )
    result = image_generation.generate_image(config, "青蓝色未来城市", "1024x1536")
    assert observed == {
        "url": "https://ws-example.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/images/generations",
        "authorization": "Bearer private-key",
        "body": {
            "model": "qwen-image-3.0-pro", "prompt": "青蓝色未来城市", "size": "1024x1536",
            "n": 1, "prompt_extend": True,
        },
    }
    assert result == {
        "url": "https://dashscope-result.oss-cn-beijing.aliyuncs.com/result.png",
        "model": "qwen-image-3.0-pro", "width": 1024, "height": 1536, "expiresInHours": 24,
    }


def test_image_endpoint_requires_login_and_key(tmp_path, monkeypatch):
    for suffix in ("PROVIDER", "BASE_URL", "API_KEY", "MODEL"):
        monkeypatch.delenv(f"MINDPILOT_IMAGE_{suffix}", raising=False)
    env_path = tmp_path / "models.json"
    write_preferences(env_path, {'providers': {'dashscope': {'name': 'dashscope', 'runtimeProvider': 'dashscope', 'apiKey': '', 'configs': {'image': {'baseUrl': 'https://example.com/compatible-mode/v1', 'model': 'qwen-image-3.0-pro'}}}}, 'active': {'image': 'dashscope'}})
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        jwt_secret="test-secret-longer-than-thirty-two-bytes-for-jwt",
        allowed_origins=("http://localhost:5173",),
        model_config_path=env_path,
    )
    with TestClient(create_app(settings)) as client:
        payload = {"prompt": "未来城市", "size": "1024x1024"}
        assert client.post("/api/v1/images/generate", json=payload).status_code == 401
        client.post("/api/v1/auth/register", json={"username": "alice", "password": "strong-password-123"})
        token = client.post("/api/v1/auth/login", json={"username": "alice", "password": "strong-password-123"}).json()["accessToken"]
        response = client.post("/api/v1/images/generate", json=payload, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 503
        assert "尚未" in response.json()["detail"]


def test_image_generation_sends_reference_and_checks_format(monkeypatch):
    observed = {}

    def respond(request):
        observed.update(json.loads(request.content))
        return httpx.Response(200, json={"data": [{"url": "https://example.aliyuncs.com/output.png"}]})

    original_client = httpx.Client
    monkeypatch.setattr(image_generation.httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(respond), **kwargs
    ))
    config = RuntimeModel("image", "dashscope", "https://ws-example.cn-beijing.maas.aliyuncs.com/compatible-mode/v1", "qwen-image-3.0-pro", "private-key")
    reference = "data:image/png;base64," + base64.b64encode(b"test image").decode()
    image_generation.generate_image(config, "调整光线", references=[reference])
    assert observed["image"] == reference
    with pytest.raises(image_generation.ImageGenerationError, match="参考图仅支持"):
        image_generation.validate_references(["https://example.com/reference.png"])


def test_image_download_restricts_hosts_and_format(monkeypatch):
    original_client = httpx.Client
    monkeypatch.setattr(image_generation.httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=image_generation.PNG_MAGIC + b"data")), **kwargs
    ))
    assert image_generation.download_image("https://result.oss-cn-beijing.aliyuncs.com/output.png").startswith(image_generation.PNG_MAGIC)
    with pytest.raises(image_generation.ImageGenerationError, match="不安全"):
        image_generation.download_image("https://untrusted.example/output.png")


def test_image_gallery_persists_and_is_private(tmp_path, monkeypatch):
    for suffix in ("PROVIDER", "BASE_URL", "API_KEY", "MODEL"):
        monkeypatch.delenv(f"MINDPILOT_IMAGE_{suffix}", raising=False)
    env_path = tmp_path / "models.json"
    write_preferences(env_path, {'providers': {'dashscope': {'name': 'dashscope', 'runtimeProvider': 'dashscope', 'apiKey': 'test-key', 'configs': {'image': {'baseUrl': 'https://example.aliyuncs.com/compatible-mode/v1', 'model': 'qwen-image-3.0-pro'}}}}, 'active': {'image': 'dashscope'}})
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        jwt_secret="test-secret-longer-than-thirty-two-bytes-for-jwt",
        allowed_origins=("http://localhost:5173",),
        model_config_path=env_path,
        data_dir=tmp_path / "data",
    )
    monkeypatch.setattr(images, "generate_image", lambda *args: {
        "url": "https://example.aliyuncs.com/output.png", "width": 1024, "height": 1024,
    })
    monkeypatch.setattr(images, "download_image", lambda url: image_generation.PNG_MAGIC + b"test")
    with TestClient(create_app(settings)) as client:
        for name in ("alice", "bob"):
            assert client.post("/api/v1/auth/register", json={"username": name, "password": "strong-password-123"}).status_code < 300
        alice = client.post("/api/v1/auth/login", json={"username": "alice", "password": "strong-password-123"}).json()["accessToken"]
        bob = client.post("/api/v1/auth/login", json={"username": "bob", "password": "strong-password-123"}).json()["accessToken"]
        alice_headers = {"Authorization": f"Bearer {alice}"}
        bob_headers = {"Authorization": f"Bearer {bob}"}
        response = client.post("/api/v1/images/generate", json={"prompt": "青蓝色球体", "references": ["data:image/png;base64,dGVzdA=="]}, headers=alice_headers)
        assert response.status_code == 200, response.text
        image_id = response.json()["id"]
        assert response.json()["mode"] == "edit"
        assert client.get("/api/v1/images", headers=alice_headers).json()["items"][0]["id"] == image_id
        assert client.get(f"/api/v1/images/{image_id}/file", headers=alice_headers).content == image_generation.PNG_MAGIC + b"test"
        assert client.get("/api/v1/images", headers=bob_headers).json()["items"] == []
        assert client.get(f"/api/v1/images/{image_id}/file", headers=bob_headers).status_code == 404
        assert client.delete(f"/api/v1/images/{image_id}", headers=bob_headers).status_code == 404
        assert client.delete(f"/api/v1/images/{image_id}", headers=alice_headers).status_code == 204
        assert client.get(f"/api/v1/images/{image_id}/file", headers=alice_headers).status_code == 404
        assert not list((tmp_path / "data" / "generated_images").rglob("*.png"))
