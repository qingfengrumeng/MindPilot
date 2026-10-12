from app.core.model_preferences import write_preferences
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.model_runtime import load_runtime_models, require_runtime_model
from app.main import create_app


def settings_for(tmp_path):
    return Settings(database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
                    jwt_secret="test-secret-longer-than-thirty-two-bytes-for-jwt",
                    allowed_origins=("http://localhost:5173",), data_dir=tmp_path,
                    model_config_path=tmp_path / "models.json")


def login(client):
    client.post("/api/v1/auth/register", json={"username": "reader", "password": "strong-password-123"})
    token = client.post("/api/v1/auth/login", json={"username": "reader", "password": "strong-password-123"}).json()["accessToken"]
    return {"Authorization": f"Bearer {token}"}


def test_shared_provider_key_runtime_activation_and_restart(tmp_path):
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings)) as client:
        headers = login(client)
        saved = client.put("/api/v1/model-configs/dashscope", headers=headers, json={
            "name": "Qwen", "apiKey": "secret-one", "configs": {
                "text": {"baseUrl": "https://example.com/v1", "model": "qwen-plus"},
                "embedding": {"baseUrl": "https://example.com/v1", "model": "qwen3.7-text-embedding", "dimensions": 1024}}})
        assert saved.status_code == 200
        assert "secret-one" not in saved.text
        assert all("apiKey" not in p and "speechApiKey" not in p for p in saved.json()["providers"])
        assert saved.json()["active"] == {}
        for category in ("text", "embedding"):
            assert client.put(f"/api/v1/model-configs/active/{category}", headers=headers, json={"providerId": "dashscope"}).status_code == 200
            assert require_runtime_model(category, settings.model_config_path).api_key == "secret-one"
        # Rotate once, applying to all categories, without rewriting per-model keys.
        assert client.put("/api/v1/model-configs/dashscope", headers=headers,
                          json={"name": "Qwen", "apiKey": "secret-two", "configs": {}}).status_code == 200
        for category in ("text", "embedding"):
            assert require_runtime_model(category, settings.model_config_path).api_key == "secret-two"
        assert settings.model_config_path.exists()
        assert not (tmp_path / '.env').exists()
        client.post("/api/v1/auth/register", json={"username": "guest", "password": "strong-password-123"})
        guest_token = client.post("/api/v1/auth/login", json={"username": "guest", "password": "strong-password-123"}).json()["accessToken"]
        guest = {"Authorization": f"Bearer {guest_token}"}
        assert not client.get("/api/v1/model-configs", headers=guest).json()["editable"]
        assert client.put("/api/v1/model-configs/dashscope", headers=guest,
                          json={"name": "Qwen", "configs": {}}).status_code == 403
        assert client.put("/api/v1/model-configs/active/text", headers=guest, json={"providerId": None}).status_code == 403
        assert client.get("/api/v1/model-configs/dashscope/models/text", headers=guest).status_code == 403
    with TestClient(create_app(settings)) as client:
        headers = login(client)
        state = client.get("/api/v1/model-configs", headers=headers)
        assert "secret-two" not in state.text
        assert state.json()["active"] == {"text": "dashscope", "embedding": "dashscope"}
        assert client.put("/api/v1/model-configs/dashscope", headers=headers,
                          json={"name": "Qwen", "clearApiKey": True}).status_code == 200
        assert not load_runtime_models(settings.model_config_path)["text"].configured
        assert not load_runtime_models(settings.model_config_path)["embedding"].configured


def test_configuration_keeps_keys_private_and_disable_does_not_fall_back(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    write_preferences(settings.model_config_path, {'providers': {'deepseek': {'name': 'deepseek', 'runtimeProvider': 'deepseek', 'apiKey': 'environment-secret', 'configs': {'text': {'baseUrl': 'https://api.deepseek.com', 'model': 'deepseek-flash'}}}}, 'active': {'text': 'deepseek'}})
    for suffix in ("PROVIDER", "BASE_URL", "MODEL", "API_KEY"):
        monkeypatch.delenv("MINDPILOT_TEXT_" + suffix, raising=False)
    original = settings.model_config_path.read_bytes()
    with TestClient(create_app(settings)) as client:
        headers = login(client)
        response = client.get("/api/v1/model-configs", headers=headers)
        assert "environment-secret" not in response.text
        assert response.json()["active"]["text"] == "deepseek"
        assert client.put("/api/v1/model-configs/active/text", headers=headers, json={"providerId": None}).status_code == 200
        assert not load_runtime_models(settings.model_config_path)["text"].configured
        assert client.put("/api/v1/model-configs/active/text", headers=headers, json={"providerId": "deepseek"}).status_code == 200
        assert require_runtime_model("text", settings.model_config_path).api_key == "environment-secret"
        assert settings.model_config_path.read_bytes() == original


def test_custom_model_switching_validation_and_model_discovery(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings)) as client:
        headers = login(client)
        assert client.put("/api/v1/model-configs/active/text", headers=headers, json={"providerId": "deepseek"}).status_code == 422
        custom = client.post("/api/v1/model-configs", headers=headers, json={"name": "Local", "apiKey": "local-secret",
             "configs": {"text": {"baseUrl": "http://localhost:1234/v1", "model": "local-model"}}}).json()["providers"][-1]
        assert custom["custom"] and custom["hasKey"]
        assert client.put("/api/v1/model-configs/active/text", headers=headers, json={"providerId": custom["id"]}).status_code == 200
        assert require_runtime_model("text", settings.model_config_path).model == "local-model"
        for url in ("file:///etc/passwd", "https://secret@host.example/v1", "https://example.com/?api_key=secret"):
            assert client.put(f"/api/v1/model-configs/{custom['id']}", headers=headers,
                json={"name": "Local", "configs": {"text": {"baseUrl": url, "model": "model"}}}).status_code == 422
        assert client.put("/api/v1/model-configs/dashscope", headers=headers, json={"name": "Qwen", "apiKey": "key",
              "configs": {"image": {"baseUrl": "https://example.com/v1", "model": "unwired-image-model"}}}).status_code == 422
        class FakeClient:
            def __init__(self, **kwargs):
                assert not kwargs["follow_redirects"] and not kwargs["trust_env"]
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def get(self, url, headers):
                assert url == "http://localhost:1234/v1/models" and headers["Authorization"] == "Bearer local-secret"
                class Response:
                    status_code = 200
                    def json(self): return {"data": [{"id": "first"}, {"id": "second"}, {"id": "first"}]}
                return Response()
        monkeypatch.setattr("app.api.routes.model_configs.httpx.Client", FakeClient)
        assert client.get(f"/api/v1/model-configs/{custom['id']}/models/text", headers=headers).json() == {"models": ["first", "second"]}
