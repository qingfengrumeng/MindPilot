"""UI state adapter. All file access and validation go through config.py."""
from pathlib import Path
from app.core.config import (MODEL_CONFIG_LOCK, ModelConfiguration, configuration_json,
                             read_model_configuration, write_model_configuration)
LOCK = MODEL_CONFIG_LOCK


def read_preferences(path: Path) -> dict:
    config = read_model_configuration(path)
    providers = {}
    for provider_id, provider in config.providers.items():
        providers[provider_id] = {"name": provider.display_name, "runtimeProvider": provider.api_family,
            "apiKey": provider.credentials.api_key.get_secret_value(),
            "speechApiKey": provider.credentials.speech_key.get_secret_value(),
            "configs": {category: {"baseUrl": model.endpoint, "model": model.model_id,
                **{("embeddingProtocol" if k == "embedding_protocol" else k): v for k, v in model.options.model_dump().items()}}
                for category, model in provider.models.items()}}
    return {"providers": providers, "active": config.model_routes,
            "integrations": configuration_json(config, masked=False)["integrations"]}


def write_preferences(path: Path, state: dict):
    document = {"format_version": 1, "model_routes": state["active"], "providers": {},
                "integrations": state.get("integrations", {})}
    for provider_id, p in state["providers"].items():
        document["providers"][provider_id] = {"display_name": p["name"], "api_family": p.get("runtimeProvider", provider_id),
            "credentials": {"api_key": p.get("apiKey", ""), "speech_key": p.get("speechApiKey", "")},
            "models": {c: {"endpoint": m["baseUrl"], "model_id": m["model"],
                "options": {"dimensions": m.get("dimensions"), "voice": m.get("voice"), "instruction": m.get("instruction"),
                            "embedding_protocol": m.get("embeddingProtocol", "compatible"), "vision": m.get("vision", False)}}
                for c, m in p["configs"].items()}}
    try:
        config = ModelConfiguration.model_validate(document)
    except ValueError:
        raise RuntimeError("模型配置校验失败，请检查接口地址、凭证和模型路由") from None
    write_model_configuration(config, path)
