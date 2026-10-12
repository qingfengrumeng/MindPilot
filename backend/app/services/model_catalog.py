"""Only categories with working backend adapters are offered."""
CATEGORIES = [
    {"id": "text", "label": "LLM", "description": "语言与多模态问答"},
    {"id": "embedding", "label": "Embedding", "description": "知识库向量检索"},
    {"id": "reranker", "label": "Rerank", "description": "检索结果重排"},
    {"id": "asr", "label": "ASR", "description": "语音识别"},
    {"id": "tts", "label": "TTS", "description": "语音合成"},
    {"id": "image", "label": "Image", "description": "海报图像生成"},
]
QWEN_HTTP = "https://dashscope.aliyuncs.com/compatible-mode/v1"
ARK_HTTP = "https://ark.cn-beijing.volces.com/api/v3"
PROVIDERS = [
    {"id": "deepseek", "name": "DeepSeek", "icon": "deepseek", "keyUrl": "https://platform.deepseek.com/api_keys",
     "defaults": {"text": {"baseUrl": "https://api.deepseek.com", "model": "deepseek-flash"}},
     "models": {"text": ["deepseek-flash"]}},
    {"id": "moonshot", "name": "Kimi", "icon": "kimi", "keyUrl": "https://platform.kimi.com/console/api-keys",
     "defaults": {"text": {"baseUrl": "https://api.moonshot.cn/v1", "model": "kimi-k3"}},
     "models": {"text": ["kimi-k3", "kimi-k2.6", "kimi-k2.7-code-highspeed"]}},
    {"id": "dashscope", "name": "Qwen · 阿里云百炼", "icon": "qwen", "keyUrl": "https://bailian.console.aliyun.com/",
     "defaults": {
         "text": {"baseUrl": QWEN_HTTP, "model": "qwen-plus"},
         "embedding": {"baseUrl": QWEN_HTTP, "model": "qwen3.7-text-embedding", "dimensions": 1024},
         "reranker": {"baseUrl": "https://dashscope.aliyuncs.com/api/v1", "model": "qwen3.7-text-rerank"},
         "asr": {"baseUrl": "", "model": "qwen3-asr-flash-realtime"},
         "tts": {"baseUrl": "", "model": "qwen-audio-3.1-tts-flash", "voice": "longanwen_v3.1"},
         "image": {"baseUrl": QWEN_HTTP, "model": "qwen-image-3.0-pro"},
     }, "models": {"text": ["qwen-plus", "qwen-max", "qwen-turbo"]}},
    {"id": "volcengine", "name": "豆包 · 火山引擎", "icon": "doubao",
     "keyUrl": "https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey",
     "speechKeyUrl": "https://console.volcengine.com/speech/new/setting/apikeys", "separateSpeechKey": True,
     "defaults": {
         "text": {"baseUrl": ARK_HTTP, "model": "doubao-seed-1-6-250615"},
         "embedding": {"baseUrl": ARK_HTTP, "model": "doubao-embedding-vision-251215", "dimensions": 1024,
                       "embeddingProtocol": "multimodal", "instruction": "Target_modality: text.\nInstruction:Represent the text for semantic retrieval\nQuery:"},
         "asr": {"baseUrl": "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async", "model": "volc.seedasr.sauc.duration"},
         "tts": {"baseUrl": "https://openspeech.bytedance.com/api/v3/tts/unidirectional", "model": "seed-tts-2.0", "voice": "zh_female_vv_uranus_bigtts"},
     }, "models": {
         "text": ["doubao-seed-1-6-250615", "doubao-seed-1-6-flash-250615"],
         "embedding": ["doubao-embedding-vision-251215", "doubao-embedding-vision-250615", "doubao-embedding-text-240515"],
         "asr": ["volc.seedasr.sauc.duration", "volc.seedasr.sauc.concurrent", "volc.bigasr.sauc.duration", "volc.bigasr.sauc.concurrent"],
         "tts": ["seed-tts-2.0", "seed-tts-1.0", "seed-tts-1.0-concurr"],
     }},
    {"id": "zhipu", "name": "GLM · 智谱", "icon": "glm", "keyUrl": "https://bigmodel.cn/usercenter/proj-mgmt/apikeys",
     "defaults": {"text": {"baseUrl": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4.7-flash"}},
     "models": {"text": ["glm-4.7-flash", "glm-4.7"]}},
    {"id": "custom", "name": "自定义接口", "icon": "custom", "keyUrl": "", "custom": True, "runtimeProvider": "openai",
     "defaults": {"text": {"baseUrl": "", "model": ""}, "embedding": {"baseUrl": "", "model": "", "dimensions": 1024}},
     "models": {}},
]
