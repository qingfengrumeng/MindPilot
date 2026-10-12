import os
import secrets
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator, model_validator


BASE_DIR = Path(__file__).resolve().parents[2]
MODEL_CONFIG_FILE = BASE_DIR.parent / ".mindpoilt" / "models.json"
LEGACY_MODEL_CONFIG_FILE = BASE_DIR / ".mindpoilt"
MODEL_CONFIG_LOCK = RLock()
MODEL_CATEGORIES = ("text", "embedding", "reranker", "asr", "tts", "image")


class SecureSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(SecureSchema):
    api_key: SecretStr = SecretStr("")
    speech_key: SecretStr = SecretStr("")

    @field_validator("api_key", "speech_key")
    @classmethod
    def safe_key(cls, value):
        key = value.get_secret_value()
        if len(key) > 4096 or any(ord(c) < 32 for c in key) or (key and set(key) <= {"•", "*"}):
            raise ValueError("无效的凭证格式")
        return value


class ModelOptions(SecureSchema):
    dimensions: int | None = Field(default=None, ge=1, le=65536)
    voice: str | None = Field(default=None, max_length=200)
    instruction: str | None = Field(default=None, max_length=2000)
    embedding_protocol: Literal["compatible", "multimodal"] = "compatible"
    vision: bool = False


class ModelEndpoint(SecureSchema):
    endpoint: str = Field(max_length=1000)
    model_id: str = Field(min_length=1, max_length=200)
    options: ModelOptions = Field(default_factory=ModelOptions)

    @field_validator("endpoint")
    @classmethod
    def safe_endpoint(cls, value):
        value = value.strip().rstrip("/")
        url = urlsplit(value)
        if url.scheme not in {"http", "https", "wss"} or not url.hostname or url.username or url.password or url.query or url.fragment or any(ord(c) < 32 for c in value):
            raise ValueError("无效的模型接口地址")
        return value

    @field_validator("model_id")
    @classmethod
    def model_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("模型名称不能为空")
        return value


class ProviderConfiguration(SecureSchema):
    display_name: str = Field(min_length=1, max_length=80)
    api_family: str = Field(min_length=1, max_length=80)
    credentials: Credentials = Field(default_factory=Credentials)
    models: dict[str, ModelEndpoint] = Field(default_factory=dict)

    @field_validator("models")
    @classmethod
    def categories(cls, value):
        if set(value) - set(MODEL_CATEGORIES):
            raise ValueError("未知的模型类别")
        return value


class SearchConfiguration(SecureSchema):
    authorization: SecretStr = SecretStr("")

    @field_validator("authorization")
    @classmethod
    def safe_authorization(cls, value):
        key = value.get_secret_value()
        if len(key) > 4096 or any(ord(c) < 32 for c in key) or (key and set(key) <= {"•", "*"}):
            raise ValueError("无效的搜索凭证")
        return value


class Integrations(SecureSchema):
    baidu_search: SearchConfiguration = Field(default_factory=SearchConfiguration)


class ModelConfiguration(SecureSchema):
    format_version: Literal[1] = 1
    model_routes: dict[str, str | None] = Field(default_factory=dict)
    providers: dict[str, ProviderConfiguration] = Field(default_factory=dict)
    integrations: Integrations = Field(default_factory=Integrations)

    @model_validator(mode="after")
    def routes(self):
        if set(self.model_routes) - set(MODEL_CATEGORIES):
            raise ValueError("未知的模型路由")
        for category, provider_id in self.model_routes.items():
            if provider_id is not None and (provider_id not in self.providers or category not in self.providers[provider_id].models):
                raise ValueError("启用的模型路由没有对应配置")
        return self


def config_path(path: Path | None = None) -> Path:
    from app.core.state_home import checked_path
    target = checked_path(path or MODEL_CONFIG_FILE)
    if target.name != "models.json" or target.is_dir():
        raise RuntimeError("模型配置只能使用受控的 models.json 文件")
    return target


def migrate_model_configuration(legacy_path=None, target_path=None):
    """Validate and relocate the credential file, preserving every original byte."""
    from app.core.state_home import checked_path, migration_lock
    with MODEL_CONFIG_LOCK:
        source = checked_path(legacy_path or LEGACY_MODEL_CONFIG_FILE)
        target = config_path(target_path)
        if source.name != ".mindpoilt":
            raise RuntimeError("无效的旧模型配置路径")
        if not source.exists():
            return
        if not source.is_file():
            raise RuntimeError("旧模型配置必须是文件")
        target.parent.mkdir(parents=True, exist_ok=True)
        with migration_lock(target.parent):
            # A second process may have completed the move while this process waited.
            if not source.exists():
                return
            try:
                if source.stat().st_size > 2 * 1024 * 1024:
                    raise ValueError()
                contents = source.read_bytes()
                ModelConfiguration.model_validate_json(contents)
            except (ValueError, OSError):
                raise RuntimeError("旧模型配置无效，迁移已停止，请检查配置格式") from None
            if target.exists():
                if target.read_bytes() != contents:
                    raise RuntimeError("新旧模型配置不同，迁移已停止以避免覆盖密钥")
                source.unlink()
            else:
                os.replace(source, target)


def read_model_configuration(path: Path | None = None) -> ModelConfiguration:
    """Trusted read boundary. Never return validation errors containing secrets."""
    with MODEL_CONFIG_LOCK:
        target = config_path(path)
        if target == MODEL_CONFIG_FILE:
            migrate_model_configuration()
        if not target.exists():
            return ModelConfiguration()
        try:
            if target.stat().st_size > 2 * 1024 * 1024:
                raise ValueError()
            return ModelConfiguration.model_validate_json(target.read_text(encoding="utf-8"))
        except (ValidationError, ValueError, OSError):
            raise RuntimeError("models.json 配置无效或无法读取，请检查格式、模型路由和接口地址") from None


def configuration_json(config: ModelConfiguration, *, masked=True) -> dict:
    result = config.model_dump(mode="json")
    for provider_id, provider in config.providers.items():
        result["providers"][provider_id]["credentials"] = {
            name: ("••••••••" if secret.get_secret_value() else "") if masked else secret.get_secret_value()
            for name, secret in (("api_key", provider.credentials.api_key), ("speech_key", provider.credentials.speech_key))}
    secret = config.integrations.baidu_search.authorization.get_secret_value()
    result["integrations"]["baidu_search"]["authorization"] = ("••••••••" if secret else "") if masked else secret
    return result


def write_model_configuration(config: ModelConfiguration, path: Path | None = None):
    with MODEL_CONFIG_LOCK:
        target = config_path(path)
        if target == MODEL_CONFIG_FILE:
            migrate_model_configuration()
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".models-", dir=target.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(configuration_json(config, masked=False), handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def persistent_secret(data_dir: Path) -> str:
    configured = os.getenv("MINDPILOT_JWT_SECRET")
    if configured:
        if len(configured.encode()) < 32:
            raise RuntimeError("MINDPILOT_JWT_SECRET must be at least 32 bytes")
        return configured
    data_dir.mkdir(parents=True, exist_ok=True)
    secret_file = data_dir / ".jwt_secret"
    try:
        descriptor = os.open(secret_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(secrets.token_urlsafe(48))
    secret = secret_file.read_text(encoding="ascii").strip()
    if len(secret.encode()) < 32:
        raise RuntimeError(f"JWT secret file is missing or incomplete: {secret_file}")
    return secret


@dataclass(frozen=True)
class Settings:
    database_url: str
    jwt_secret: str
    allowed_origins: tuple[str, ...]
    access_minutes: int = 15
    refresh_days: int = 30
    secure_cookie: bool = False
    model_config_path: Path = MODEL_CONFIG_FILE
    data_dir: Path = BASE_DIR / "data"
    document_chunk_size: int = 1000
    state_dir: Path | None = None


def load_settings() -> Settings:
    from app.core.state_home import prepare_state_home
    data_dir = Path(os.getenv("MINDPILOT_DATA_DIR", str(BASE_DIR / "data"))).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    configured_database = os.getenv("MINDPILOT_DATABASE_URL")
    state_dir, _ = prepare_state_home(BASE_DIR.parent, data_dir)
    database = data_dir / "mindpoilt.sqlite"
    migrate_model_configuration()
    origins = os.getenv("MINDPILOT_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return Settings(
        database_url=configured_database or f"sqlite:///{database.as_posix()}",
        jwt_secret=persistent_secret(data_dir),
        allowed_origins=tuple(origin.strip() for origin in origins.split(",") if origin.strip()),
        secure_cookie=os.getenv("MINDPILOT_SECURE_COOKIE", "false").lower() == "true",
        model_config_path=MODEL_CONFIG_FILE,
        data_dir=data_dir,
        document_chunk_size=max(100, min(int(os.getenv("MINDPILOT_DOCUMENT_CHUNK_SIZE", "1000")), 10_000)),
        state_dir=state_dir,
    )
