from copy import deepcopy
from uuid import uuid4
from urllib.parse import urlsplit, urlunsplit
from time import perf_counter

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.responses import Response as AudioResponse
from pydantic import BaseModel, Field, field_validator
from typing import Literal
from sqlalchemy import select

from app.api.deps import CurrentContext, Db
from app.db.models import User
from app.core.model_preferences import LOCK, read_preferences, write_preferences
from app.core.config import configuration_json, read_model_configuration
from app.core.model_runtime import MODEL_CATEGORIES
from app.core.model_runtime import RuntimeModel
from app.services.model_diagnostics import probe_model
from app.services.model_catalog import CATEGORIES, PROVIDERS
from app.services.tts_voices import fetch_system_voices, VoiceListError
from app.services.tts_synthesis import stream_mp3
from app.services.model_comparison import compare_text
from app.services.evaluation_models import TrialModel, resolve_trial

router = APIRouter(prefix="/model-configs", tags=["model-configs"])


def can_edit(db, context):
    # Service-wide credentials belong to the local installation's first account.
    owner = db.scalar(select(User.id).order_by(User.created_at, User.id).limit(1))
    return owner == context[0].id


def require_owner(db, context):
    if not can_edit(db, context):
        raise HTTPException(403, "本机共享模型配置仅主账户可修改，请使用首次注册的账户")


class ModelConfig(BaseModel):
    baseUrl: str = Field(max_length=1000)
    model: str = Field(min_length=1, max_length=200)
    dimensions: int | None = Field(default=None, ge=1, le=65536)
    voice: str | None = Field(default=None, max_length=200)
    instruction: str | None = Field(default=None, max_length=2000)
    embeddingProtocol: Literal["compatible", "multimodal"] = "compatible"
    vision: bool = False

    @field_validator("baseUrl")
    @classmethod
    def valid_url(cls, value):
        value = value.strip().rstrip("/")
        url = urlsplit(value)
        if url.scheme not in {"http", "https", "wss"} or not url.hostname or url.username or url.password or url.query or url.fragment or "{" in value:
            raise ValueError("无效的接口地址")
        return value

    @field_validator("model")
    @classmethod
    def trim_model(cls, value):
        if not value.strip():
            raise ValueError("模型名称不能为空")
        return value.strip()


class ProviderWrite(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    apiKey: str | None = Field(default=None, max_length=4096)
    clearApiKey: bool = False
    speechApiKey: str | None = Field(default=None, max_length=4096)
    clearSpeechApiKey: bool = False
    configs: dict[str, ModelConfig] = Field(default_factory=dict)

    @field_validator("apiKey", "speechApiKey")
    @classmethod
    def valid_key(cls, value):
        if value is not None and any(ord(c) < 32 for c in value):
            raise ValueError("密钥格式不正确")
        return value.strip() if value else None


class Activation(BaseModel):
    providerId: str | None = None


def validate_config(category, config, runtime_provider):
    if category not in MODEL_CATEGORIES:
        raise HTTPException(422, "不支持的模型类别")
    if runtime_provider == "volcengine" and category in {"asr", "tts"}:
        preset = next(p for p in PROVIDERS if p["id"] == "volcengine")
        if config["model"] not in preset["models"][category]:
            raise HTTPException(422, "请选择已接入的豆包语音资源 ID")
    elif category not in {"text", "embedding"}:
        defaults = next(p for p in PROVIDERS if p["id"] == "dashscope")["defaults"]
        if runtime_provider != "dashscope" or config["model"] != defaults[category]["model"]:
            raise HTTPException(422, "此类别请使用当前已接入的百炼模型")
    scheme = urlsplit(config["baseUrl"]).scheme
    websocket_category = category == "asr" or (category == "tts" and runtime_provider != "volcengine")
    if websocket_category and scheme != "wss":
        raise HTTPException(422, "语音实时接口需要 wss:// 地址")
    if not websocket_category and scheme not in {"http", "https"}:
        raise HTTPException(422, "当前类别需要 HTTP(S) 接口地址")
    if category == "embedding":
        if not config.get("dimensions"):
            raise HTTPException(422, "请填写向量维度")
        if runtime_provider == "dashscope" and (config["model"] != "qwen3.7-text-embedding" or config["dimensions"] not in {256, 512, 768, 1024, 1536, 2048, 2560}):
            raise HTTPException(422, "请填写当前百炼模型支持的名称和向量维度")
        if runtime_provider == "volcengine" and config.get("embeddingProtocol") == "multimodal" and config["dimensions"] not in {1024, 2048}:
            raise HTTPException(422, "豆包多模态向量维度请选择 1024 或 2048")
        if config.get("embeddingProtocol") == "multimodal" and runtime_provider != "volcengine":
            raise HTTPException(422, "多模态向量协议目前用于火山方舟")


def state_for(request):
    path = request.app.state.settings.model_config_path
    state = read_preferences(path)
    return path, state


def public_state(request):
    _, state = state_for(request)
    providers = deepcopy(PROVIDERS)
    known = {p["id"] for p in providers}
    for provider_id, saved in state["providers"].items():
        if provider_id not in known:
            providers.append({"id": provider_id, "name": saved["name"], "icon": "custom", "keyUrl": "",
                              "defaults": {}, "models": {}, "custom": True})
    for provider in providers:
        # Available model options are fetched explicitly from the vendor, never presets.
        provider.pop('models', None)
        saved = state["providers"].get(provider["id"], {})
        provider["name"] = saved.get("name", provider["name"])
        provider["configs"] = saved.get("configs", {})
        provider["hasKey"] = bool(saved.get("apiKey"))
        provider["hasSpeechKey"] = bool(saved.get("speechApiKey"))
        provider["saved"] = bool(saved.get("configs"))
    return {"categories": CATEGORIES, "providers": providers, "active": state["active"], "scope": "local-service", "configFile": ".mindpoilt/models.json",
            "document": configuration_json(read_model_configuration(request.app.state.settings.model_config_path))}


@router.get("")
def list_configs(request: Request, context: CurrentContext, db: Db):
    return {**public_state(request), "editable": can_edit(db, context)}


@router.get("/document")
def get_document(request: Request, response: Response, context: CurrentContext, db: Db):
    response.headers["Cache-Control"] = "no-store"
    return configuration_json(read_model_configuration(request.app.state.settings.model_config_path))


class ModelComparison(BaseModel):
    providerId: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=32000)
    systemPrompt: str = Field(default="", max_length=8000)
    maxTokens: int = Field(default=2048, ge=16, le=16384)
    temperature: float | None = Field(default=None, ge=0, le=2)

    @field_validator("model", "prompt")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("内容不能为空")
        return value.strip()


@router.post("/compare")
def compare_model(payload: ModelComparison, request: Request, context: CurrentContext, db: Db):
    require_owner(db, context)
    runtime = resolve_trial(request.app.state.settings.model_config_path,
                            TrialModel(providerId=payload.providerId, model=payload.model), "text")
    # Snapshot validated saved credentials; testing a model never saves or activates it.
    return StreamingResponse(compare_text(runtime, prompt=payload.prompt,
                                           system_prompt=payload.systemPrompt.strip(),
                                           max_tokens=payload.maxTokens, temperature=payload.temperature),
                             media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.post("")
def add_provider(payload: ProviderWrite, request: Request, context: CurrentContext, db: Db):
    require_owner(db, context)
    if set(payload.configs) - {"text", "embedding"}:
        raise HTTPException(422, "自定义兼容接口目前支持语言和向量模型")
    for category, config in payload.configs.items():
        validate_config(category, config.model_dump(), "openai")
    with LOCK:
        path, state = state_for(request)
        provider_id = "custom-" + uuid4().hex[:12]
        state["providers"][provider_id] = {"name": payload.name.strip(), "runtimeProvider": "openai", "apiKey": payload.apiKey or "",
                                         "configs": {k: v.model_dump() for k, v in payload.configs.items()}}
        write_preferences(path, state)
    return public_state(request)


@router.put("/{provider_id}")
def save_provider(provider_id: str, payload: ProviderWrite, request: Request, context: CurrentContext, db: Db):
    require_owner(db, context)
    with LOCK:
        path, state = state_for(request)
        preset = next((p for p in PROVIDERS if p["id"] == provider_id), None)
        if not preset and provider_id not in state["providers"]:
            raise HTTPException(404, "厂商配置不存在")
        allowed = set(preset["defaults"]) if preset else {"text", "embedding"} | set(state["providers"][provider_id]["configs"])
        if set(payload.configs) - allowed:
            raise HTTPException(422, "当前厂商不支持此模型类别")
        if payload.clearApiKey and payload.apiKey:
            raise HTTPException(422, "清除密钥时不能同时填写新密钥")
        if payload.clearSpeechApiKey and payload.speechApiKey:
            raise HTTPException(422, "清除语音密钥时不能同时填写新密钥")
        if (payload.speechApiKey or payload.clearSpeechApiKey) and provider_id != "volcengine":
            raise HTTPException(422, "此厂商使用统一 API Key")
        provider = state["providers"].setdefault(provider_id, {"runtimeProvider": (preset or {}).get("runtimeProvider", provider_id), "configs": {}})
        for category, config in payload.configs.items():
            validate_config(category, config.model_dump(), provider.get("runtimeProvider", provider_id))
        provider["name"] = payload.name.strip()
        if payload.clearApiKey:
            provider["apiKey"] = ""
            for category, active in list(state["active"].items()):
                if active == provider_id:
                    if provider_id == "volcengine" and category in {"asr", "tts"}:
                        continue
                    state["active"][category] = None
        elif payload.apiKey:
            provider["apiKey"] = payload.apiKey
        if payload.clearSpeechApiKey:
            provider["speechApiKey"] = ""
            for category in ("asr", "tts"):
                if state["active"].get(category) == provider_id:
                    state["active"][category] = None
        elif payload.speechApiKey:
            provider["speechApiKey"] = payload.speechApiKey
        provider["configs"].update({k: v.model_dump() for k, v in payload.configs.items()})
        write_preferences(path, state)
    return public_state(request)


@router.put("/active/{category}")
def activate(category: str, payload: Activation, request: Request, context: CurrentContext, db: Db):
    require_owner(db, context)
    if category not in MODEL_CATEGORIES:
        raise HTTPException(422, "不支持的模型类别")
    with LOCK:
        path, state = state_for(request)
        if payload.providerId is not None:
            provider = state["providers"].get(payload.providerId, {})
            config = provider.get("configs", {}).get(category, {})
            key_field = "speechApiKey" if payload.providerId == "volcengine" and category in {"asr", "tts"} else "apiKey"
            if not provider.get(key_field) or not config.get("baseUrl") or not config.get("model"):
                raise HTTPException(422, "请先保存接口地址、模型名称和厂商 API Key")
            validate_config(category, config, provider.get("runtimeProvider"))
        state["active"][category] = payload.providerId
        write_preferences(path, state)
    return public_state(request)


class ModelDiscovery(BaseModel):
    baseUrl: str = Field(max_length=1000)
    apiKey: str | None = Field(default=None, max_length=4096)

    @field_validator('baseUrl')
    @classmethod
    def valid_url(cls, value):
        return ModelConfig.valid_url(value)

    @field_validator('apiKey')
    @classmethod
    def valid_key(cls, value):
        return ProviderWrite.valid_key(value)


class VoiceDiscovery(BaseModel):
    model: str = Field(min_length=1, max_length=200)

    @field_validator('model')
    @classmethod
    def trim_model(cls, value):
        return ModelConfig.trim_model(value)


class VoicePreview(ModelDiscovery):
    model: str = Field(min_length=1, max_length=200)
    voice: str = Field(min_length=1, max_length=200)

    @field_validator('model', 'voice')
    @classmethod
    def trim_value(cls, value):
        return ModelConfig.trim_model(value)


@router.post('/{provider_id}/voices/tts/preview')
def preview_tts_voice(provider_id: str, payload: VoicePreview, request: Request, context: CurrentContext, db: Db):
    require_owner(db, context)
    if provider_id != 'dashscope':
        raise HTTPException(422, '当前厂商尚未接入音色试听')
    _, state = state_for(request)
    key = payload.apiKey or state['providers'].get(provider_id, {}).get('apiKey', '')
    if not key or key == 'CHANGE_ME':
        raise HTTPException(422, '请填写厂商 API Key 后试听')
    runtime = RuntimeModel('tts', 'dashscope', payload.baseUrl, payload.model, key, voice=payload.voice)
    try:
        stream = stream_mp3(runtime, '你好，我是你的语音助手，很高兴为你服务。')
        chunks, size = [], 0
        try:
            for chunk in stream:
                size += len(chunk)
                if size > 3 * 1024 * 1024:
                    raise ValueError('试听音频过大')
                chunks.append(chunk)
        finally:
            stream.close()
        if not size:
            raise ValueError('未返回试听音频')
        return AudioResponse(b''.join(chunks), media_type='audio/mpeg', headers={'Cache-Control':'no-store'})
    except Exception:
        raise HTTPException(502, '无法生成试听音频，请检查当前 TTS 型号、接口地址、音色和密钥') from None


@router.post('/{provider_id}/voices/tts')
def discover_tts_voices(provider_id: str, payload: VoiceDiscovery, response: Response, context: CurrentContext, db: Db):
    require_owner(db, context)
    response.headers['Cache-Control'] = 'no-store'
    if provider_id != 'dashscope':
        raise HTTPException(422, '当前厂商尚未接入音色列表，可手动填写音色 ID')
    try:
        return fetch_system_voices(payload.model)
    except VoiceListError as exc:
        raise HTTPException(502, str(exc)) from None


def validate_discovery(category, base_url, api_key, provider_id=None):
    if category not in MODEL_CATEGORIES:
        raise HTTPException(422, "不支持的模型类别")
    if not api_key or api_key == 'CHANGE_ME':
        raise HTTPException(422, '请填写厂商API Key')
    if provider_id == 'dashscope' and category in {'asr', 'tts'}:
        parts = urlsplit(base_url or '')
        if parts.scheme in {'http', 'https'} or (parts.scheme == 'wss' and parts.path in {'/api-ws/v1/realtime', '/api-ws/v1/inference'}):
            return
        raise HTTPException(422, '请填写有效的百炼语音接口地址')
    if category not in {'text', 'embedding', 'image', 'reranker'} or urlsplit(base_url or '').scheme not in {'http', 'https'}:
        raise HTTPException(422, '当前类别尚未接入厂商模型列表接口，请手动填写模型名称')


def matches_model_category(row, category):
    if category not in {'embedding', 'reranker', 'image', 'asr', 'tts'}:
        return True
    name = str(row.get('id') or row.get('model') or '').lower()
    types = []
    for field in ('capabilities', 'type', 'model_type', 'task', 'pipeline_tag'):
        value = row.get(field, [])
        types.extend(value if isinstance(value, list) else [value])
    types = {str(value).lower().replace('_', '-') for value in types}
    if category == 'asr':
        return bool(types & {'asr', 'realtime-asr', 'speech-recognition', 'automatic-speech-recognition', 'speech-to-text'}) or 'asr' in name or name.split('/')[-1].startswith(('paraformer', 'whisper'))
    if category == 'tts':
        return bool(types & {'tts', 'realtime-text-to-speech', 'text-to-speech', 'speech-synthesis'}) or 'tts' in name or name.split('/')[-1].startswith(('cosyvoice', 'sambert'))
    if category == 'image':
        if types & {'ig', 'image-generation', 'text-to-image', 'image-to-image'}:
            return True
        metadata = row.get('inference_metadata')
        if isinstance(metadata, dict) and 'Image' in (metadata.get('response_modality') or []):
            return True
        # Image input/visual understanding is not image generation.
        if types & {'vu', 'vg', 'tr', 'me', 'embedding', 'text-embedding', 'rerank', 'reranker'}:
            return False
        if any(token in name for token in ('embedding', 'rerank', 'vision', 'video')):
            return False
        return name.split('/')[-1].startswith(('qwen-image', 'wanx', 'flux', 'stable-diffusion',
                                              'dall-e', 'gpt-image', 'seedream', 'cogview',
                                              'hunyuan-image', 'kolors', 'imagen'))
    embedding = bool(types & {'tr', 'me', 'embedding', 'embeddings', 'text-embedding', 'multimodal-embedding', 'feature-extraction'})
    reranker = bool(types & {'rerank', 'reranker', 'reranking', 'text-rerank'})
    if 'rerank' in name or reranker:
        return category == 'reranker'
    if embedding or 'embed' in name or name.split('/')[-1].startswith(('bge-', 'gte-', 'e5-', 'jina-embeddings', 'all-minilm', 'all-mpnet')):
        return category == 'embedding'
    return False


def matches_speech_endpoint(row, category, base_url):
    parts = urlsplit(base_url)
    if category not in {'asr', 'tts'} or parts.scheme != 'wss':
        return True
    name = str(row.get('id') or row.get('model') or '').lower()
    capabilities = row.get('capabilities') or []
    realtime = ('realtime-asr' if category == 'asr' else 'realtime-text-to-speech') in {str(value).lower() for value in capabilities}
    # Qwen session models use /realtime; task-based speech families use /inference.
    realtime = realtime or (name.split('/')[-1].startswith('qwen') and 'realtime' in name)
    return realtime if parts.path == '/api-ws/v1/realtime' else not realtime


def discover_models(base_url, api_key, category='text', provider_id=None):
    if not base_url or not api_key or api_key == 'CHANGE_ME':
        raise HTTPException(422, '请填写接口地址与API Key')
    try:
        models, cursors, cursor = [], set(), None
        native = provider_id == 'dashscope' and category in {'embedding', 'reranker', 'image', 'asr', 'tts'}
        endpoint = base_url.rstrip('/')
        if native:
            parts = urlsplit(endpoint)
            if category in {'asr', 'tts'} and parts.scheme == 'wss':
                endpoint = urlunsplit(('https', parts.netloc, '/api/v1', '', ''))
            for suffix in ('/compatible-mode/v1', '/compatible-api/v1'):
                if endpoint.endswith(suffix):
                    endpoint = endpoint[:-len(suffix)] + '/api/v1'
                    break
        page_no, seen_rows = 1, 0
        deadline = perf_counter() + 45
        with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
            while True:
                if perf_counter() > deadline:
                    raise HTTPException(504, "获取完整模型列表超时，请稍后重试")
                kwargs = {'params': {'page_no': page_no, 'page_size': 100}} if native else ({"params": {"after": cursor}} if cursor else {})
                response = client.get(endpoint + "/models", headers={"Authorization": "Bearer " + api_key}, **kwargs)
                if response.status_code >= 300:
                    raise HTTPException(502, "获取模型列表失败，请检查 API Key 和接口地址")
                body = response.json()
                output = body.get('output')
                rows = output.get('models') if isinstance(output, dict) else body.get('data')
                if not isinstance(rows, list):
                    raise HTTPException(502, "厂商返回的模型列表格式不正确")
                page = [row.get('id') or row.get('model') for row in rows if isinstance(row, dict) and isinstance(row.get('id') or row.get('model'), str)]
                models.extend(row.get('id') or row.get('model') for row in rows if isinstance(row, dict)
                              and isinstance(row.get('id') or row.get('model'), str) and matches_model_category(row, category)
                              and matches_speech_endpoint(row, category, base_url))
                if isinstance(output, dict):
                    seen_rows += len(rows)
                    total = output.get('total')
                    if not isinstance(total, int) or total < 0:
                        raise HTTPException(502, '厂商返回的模型列表分页信息无效')
                    if seen_rows >= total:
                        break
                    if not rows or page_no >= 100:
                        raise HTTPException(502, '厂商返回的模型列表分页信息无效')
                    native = True
                    page_no += 1
                    continue
                if not body.get('has_more'):
                    break
                cursor = body.get('last_id') or (page[-1] if page else None)
                if not isinstance(cursor, str) or cursor in cursors or len(cursors) >= 100:
                    raise HTTPException(502, "厂商返回的模型列表分页信息无效")
                cursors.add(cursor)
        return {"models": list(dict.fromkeys(models))}
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        raise HTTPException(502, "无法获取模型列表，可手动填写模型名称") from None


@router.get("/{provider_id}/models/{category}")
def fetch_models(provider_id: str, category: str, request: Request, response: Response, context: CurrentContext, db: Db):
    require_owner(db, context)
    response.headers['Cache-Control'] = 'no-store'
    _, state = state_for(request)
    provider = state['providers'].get(provider_id, {})
    config = provider.get('configs', {}).get(category, {})
    key_field = 'speechApiKey' if provider_id == 'volcengine' and category in {'asr', 'tts'} else 'apiKey'
    validate_discovery(category, config.get('baseUrl'), provider.get(key_field), provider_id)
    return discover_models(config.get('baseUrl'), provider.get(key_field), category, provider_id)


@router.post("/{provider_id}/models/{category}")
def discover_draft_models(provider_id: str, category: str, payload: ModelDiscovery, request: Request, response: Response, context: CurrentContext, db: Db):
    require_owner(db, context)
    response.headers['Cache-Control'] = 'no-store'
    _, state = state_for(request)
    preset = next((p for p in PROVIDERS if p['id'] == provider_id), None)
    if not preset and provider_id not in state['providers']:
        raise HTTPException(404, '厂商配置不存在')
    if preset and category not in preset['defaults']:
        raise HTTPException(422, '当前厂商不支持此模型类别')
    key_field = 'speechApiKey' if provider_id == 'volcengine' and category in {'asr', 'tts'} else 'apiKey'
    key = payload.apiKey or state['providers'].get(provider_id, {}).get(key_field, '')
    validate_discovery(category, payload.baseUrl, key, provider_id)
    return discover_models(payload.baseUrl, key, category, provider_id)


@router.post("/{provider_id}/test/{category}")
def test_connection(provider_id: str, category: str, payload: ProviderWrite, request: Request, context: CurrentContext, db: Db):
    require_owner(db, context)
    _, state = state_for(request)
    preset = next((p for p in PROVIDERS if p['id'] == provider_id), None)
    provider = state['providers'].get(provider_id, {})
    if not provider and not preset:
        raise HTTPException(404, '厂商配置不存在')
    if category not in payload.configs or (preset and category not in preset['defaults']):
        raise HTTPException(422, '请填写对应类别的模型配置')
    config = payload.configs[category].model_dump()
    family = provider.get('runtimeProvider', (preset or {}).get('runtimeProvider', provider_id))
    validate_config(category, config, family)
    speech = provider_id == 'volcengine' and category in {'asr', 'tts'}
    key = (payload.speechApiKey if speech else payload.apiKey) or provider.get('speechApiKey' if speech else 'apiKey', '')
    if not key or (payload.clearSpeechApiKey if speech else payload.clearApiKey):
        raise HTTPException(422, '请填写对应的厂商API Key')
    runtime = RuntimeModel(category, family, config['baseUrl'], config['model'], key, config.get('dimensions'),
                           config.get('voice'), config.get('instruction'), config.get('embeddingProtocol', 'compatible'))
    if not runtime.configured:
        raise HTTPException(422, '请填写完整的模型配置与有效API Key')
    try:
        return probe_model(runtime)
    except Exception:
        # Vendor exceptions may contain headers or echoed credentials.
        raise HTTPException(502, '连接测试失败，请检查接口地址、API Key、模型权限与网络') from None
