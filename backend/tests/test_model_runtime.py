from app.core.model_preferences import write_preferences
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.model_runtime import load_runtime_models, require_runtime_model
from app.main import create_app


def test_model_settings_use_config_and_ignore_environment(tmp_path, monkeypatch):
    path = tmp_path / "models.json"
    write_preferences(path, {'providers': {'deepseek': {'name': 'deepseek', 'runtimeProvider': 'deepseek', 'apiKey': 'CHANGE_ME', 'configs': {'text': {'baseUrl': 'https://api.deepseek.com', 'model': 'deepseek-flash'}}}}, 'active': {'text': 'deepseek'}})
    for suffix in ("PROVIDER", "BASE_URL", "MODEL", "API_KEY"):
        monkeypatch.delenv(f"MINDPILOT_TEXT_{suffix}", raising=False)

    model = load_runtime_models(path)["text"]
    assert (model.provider, model.base_url, model.model) == (
        "deepseek", "https://api.deepseek.com", "deepseek-flash"
    )
    assert not model.configured

    monkeypatch.setenv("MINDPILOT_TEXT_API_KEY", "test-secret")
    assert not load_runtime_models(path)["text"].configured
    write_preferences(path, {'providers': {'deepseek': {'name': 'deepseek', 'runtimeProvider': 'deepseek', 'apiKey': 'test-secret', 'configs': {'text': {'baseUrl': 'https://api.deepseek.com', 'model': 'deepseek-flash'}}}}, 'active': {'text': 'deepseek'}})
    assert require_runtime_model("text", path).api_key == "test-secret"
    assert not load_runtime_models(path)["asr"].configured


def test_model_configuration_requires_authentication(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        jwt_secret="test-secret-longer-than-thirty-two-bytes-for-jwt",
        allowed_origins=("http://localhost:5173",),
        model_config_path=tmp_path / "models.json",
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/model-configs").status_code == 401
        response = client.put("/api/v1/model-configs/text", json={
            "baseUrl": "https://example.com", "apiKey": "would-be-secret"
        })
        assert response.status_code == 401
        assert not settings.model_config_path.exists()
