"""Read enabled model settings through the secure config.py boundary."""

from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import MODEL_CONFIG_FILE, MODEL_CATEGORIES


@dataclass(frozen=True)
class RuntimeModel:
    category: str
    provider: str
    base_url: str
    model: str
    api_key: str = field(repr=False)
    dimensions: int | None = None
    voice: str | None = None
    instruction: str | None = None
    embedding_protocol: str = "compatible"

    @property
    def configured(self) -> bool:
        return bool(
            self.base_url and self.model and self.api_key
            and self.api_key != "CHANGE_ME"
            and (self.provider or self.category in {"text", "embedding"})
        )


def load_runtime_models(config_path: Path | None = None) -> dict[str, RuntimeModel]:
    from app.core.model_preferences import read_preferences
    result = {category: RuntimeModel(category, "", "", "", "") for category in MODEL_CATEGORIES}
    state = read_preferences(config_path or MODEL_CONFIG_FILE)
    for category, provider_id in state["active"].items():
        if category not in MODEL_CATEGORIES:
            continue
        if provider_id is None:
            result[category] = RuntimeModel(category, "", "", "", "")
            continue
        provider = state["providers"].get(provider_id, {})
        config = provider.get("configs", {}).get(category)
        if not config:
            raise RuntimeError("启用的模型配置不完整，请重新保存模型配置")
        result[category] = RuntimeModel(
            category, provider.get("runtimeProvider", provider_id), config["baseUrl"],
            config["model"], provider.get("speechApiKey", "") if provider_id == "volcengine" and category in {"asr", "tts"} else provider.get("apiKey", ""),
            config.get("dimensions"), config.get("voice"), config.get("instruction"),
            config.get("embeddingProtocol", "compatible"),
        )
    return result


def require_runtime_model(category: str, config_path: Path | None = None) -> RuntimeModel:
    """Give backend adapters a single validated entry point for model settings."""
    if category not in MODEL_CATEGORIES:
        raise ValueError("不支持的模型类型")
    model = load_runtime_models(config_path)[category]
    if not model.configured:
        raise RuntimeError(f"{category} 模型尚未完整配置，请在模型配置中保存并启用")
    return model
