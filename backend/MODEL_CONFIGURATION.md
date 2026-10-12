# 模型配置

所有模型配置统一保存在项目根目录 `.mindpoilt/models.json`（严格 JSON）。网页的完整表单会自动保存，也可以点击“保存配置”。保存和启用分开：每个用途通过 `model_routes` 选择一个厂商，`null` 表示停用。

启动时将旧 `backend/.mindpoilt` 校验后原子移动到新路径，保留全部模型参数、密钥和搜索凭证。迁移不改写原文件字节；新旧文件不同或旧配置无效时拒绝覆盖。旧文件仅作为迁移来源，日常读写使用 `models.json`。

```json
{
  "format_version": 1,
  "model_routes": { "text": "deepseek", "embedding": null },
  "providers": {
    "deepseek": {
      "display_name": "DeepSeek",
      "api_family": "deepseek",
      "credentials": { "api_key": "实际密钥", "speech_key": "" },
      "models": {
        "text": {
          "endpoint": "https://api.deepseek.com",
          "model_id": "deepseek-flash",
          "options": { "vision": false }
        }
      }
    }
  },
  "integrations": { "baidu_search": { "authorization": "" } }
}
```

`providers` 按厂商集中管理凭证；`models` 按 `text`、`embedding`、`reranker`、`asr`、`tts`、`image` 分类保存参数。`options` 支持 `dimensions`、`voice`、`instruction`、`embedding_protocol`、`vision`。火山引擎的方舟模型使用 `api_key`，语音模型使用 `speech_key`，分别在服务内共用。

调用链：功能接口 → `model_runtime.py` → `model_preferences.py`（字段转换）→ `config.py`（验证与文件访问）→ `.mindpoilt/models.json`。每次请求读取当前配置，不使用模型环境变量，也不回退到 `.env`。现有 `.env` 作为旧配置保留，修改它不会影响模型调用。

`config.py` 限制文件名、拒绝路径中的符号链接和超大文件，校验版本、字段、模型路由和接口地址，使用 `SecretStr` 避免凭证出现在对象打印中。写入采用临时文件和原子替换；临时文件仅文件所有者可读写（支持 POSIX 权限的平台）。不完整或无效配置会被拒绝。网页只接收脱敏结果，只有主账户能修改配置。密钥以实际值存储在本地文件，JSON 预览中的圆点不能作为真实凭证。文件受根目录 `.gitignore` 保护。

字段组织参考 [Claude Code 的 JSON 配置与项目作用域](https://code.claude.com/docs/en/settings)，针对本项目的多厂商和多用途模型设计，不直接复制其字段。

## 模型对比测试

账户菜单中的“模型对比测试”打开大尺寸界面，提供 LLM 性能对比与 RAG 评测。LLM 支持用户配置 1—12 个具体型号及 1—6 个同时请求；可以对比同一厂商的多个型号。添加测试模型时，弹窗只提供已保存密钥和对应接口的厂商。所有测试项使用相同问题、系统提示词与输出参数，并独立显示流式回答、思考过程（厂商提供时）、首字耗时、总耗时、token 用量和平均输出速率。支持单独测试、重试、停止与复制。

测试复用 `models.json` 中已保存的接口和厂商密钥，允许覆盖本次请求的模型名称，不保存覆盖值、不切换启用路由、不创建聊天或记忆记录。模型选项只在点击“获取模型列表”后通过厂商 API 获取，留在当前弹窗内存中，关闭或切换厂商后丢弃；未获取时可以手动填写。

RAG 页提供独立临时语料、可修订的黄金问答与相关性标注、Embedding / 分块 / top-k / 重排方案、真实检索指标和可选的模型事实核验。测试数据进入业务目录，凭证仍通过安全配置层读取。详见 [RAG_EVALUATION.md](RAG_EVALUATION.md)。

接口 `POST /api/v1/model-configs/compare` 仅主账户可调用，返回 NDJSON 流。请求包含 `providerId`、`model`、`prompt`，可选 `systemPrompt`、`maxTokens`（默认 2048，范围 16—16384）、`temperature`（留空使用厂商默认值）。真实凭证不由前端传入。单次测试最多 120 秒，断开连接会取消上游请求，错误不回传厂商原始正文或秘密字段。

首字耗时指服务端收到回答首个文本片段的时间，思考片段不计作回答首字。输出速率按厂商返回的输出 token 除以总耗时计算，不能作为排除网络和排队影响后的纯生成速度。厂商没有返回用量时显示“—”，不推算或编造 token 数。测试会实际调用模型并产生厂商规定的用量。
