# MindPilot FastAPI 后端

当前实现本地账号和会话记录。账号、登录状态、个人资料与文件索引默认保存在 `backend/data/mindpoilt.sqlite`；会话、工具任务、上下文和记忆索引保存在项目根目录 `.mindpoilt/state_1.sqlite`。启动时自动迁移旧混合库并执行 Alembic 升级，混合库备份保存在 `backend/data/backups/`。`backend/data/.jwt_secret` 保持原位置，完整布局见 [本地数据隔离](DATA_STORAGE.md)。

会话原始事件、工具输入输出和上下文压缩记录追加保存到 `.mindpoilt/sessions/年/月/日/rollout-时间-会话ID.jsonl`；SQLite 保留查询投影、索引和任务状态，根目录 `session_index.jsonl` 提供可重建的会话目录。长期记忆写入 `.mindpoilt/memories/` 下按用户隔离的 Markdown 文件。上下文压缩后保留最近十轮完整内容，窗口预算与后台提取参数配置在 `.mindpoilt/config.toml` 的 `[memory]` 段，详见 [会话与记忆说明](../.mindpoilt/README.md)。旧状态目录和 JSON 策略自动迁移，压缩不会删除原始记录。

## 启动

模型在账户菜单 →「模型配置」中按用途和厂商管理，所有配置统一保存到项目根目录 `.mindpoilt/models.json`。完整表单自动保存，保存与启用分开，每个类别同时启用一个模型。配置经过 `app/core/config.py` 校验后供运行时读取，无需重启。首次注册的主账户可修改，其他登录账户只能查看；前端 JSON 预览始终对已保存的密钥脱敏，不写入浏览器存储。现有 `.env` 保留，但模型运行不再读取它或模型环境变量。详见 [配置文件格式与安全边界](MODEL_CONFIGURATION.md)。

账户、密码哈希、登录会话和失败次数存储在 `backend/data/mindpoilt.sqlite`。JWT 签名密钥位于 `backend/data/.jwt_secret`；浏览器使用内存中的访问令牌与 HttpOnly 刷新 Cookie。详见 [登录信息存储与 Codex 对照](AUTH_STORAGE.md)。

火山引擎支持 LLM、Embedding、ASR、TTS：方舟 `api_key` 供 LLM / Embedding 共用，豆包语音 `speech_key` 供 ASR / TTS 共用。豆包 ASR 使用原生二进制 WebSocket，TTS 使用 HTTP 流式 MP3。Embedding 支持兼容 `/embeddings` 或原生 `/embeddings/multimodal` 协议，原生协议每段文本分别请求。自定义兼容接口支持语言与向量模型。更换向量模型或维度后需重新向量化资料。

Embedding 使用阿里云百炼 `qwen3.7-text-embedding`。在模型配置的 Embedding 分类下填写业务空间接口地址和厂商密钥；默认输出 1024 维浮点向量，可在向量维度字段调整。上传 PDF、TXT 或 Markdown 时只将原文件保存到 `backend/data/documents/<用户 ID>/`，不会等待解析和向量化。点击资料行内的「向量化」按钮后，后台工作线程会用 `pdfplumber` 读取 PDF 文本，按 `MINDPILOT_DOCUMENT_CHUNK_SIZE`（默认 1000 字符）切分，并将分块和向量写入本地持久化 ChromaDB，同时把文档与分块元数据写入 SQLite。列表显示文本解析、Chunk 切分、文本向量化、向量化完成等进度；切分完成后才显示分块数。Embedding 服务暂时不可用时，会退化到轻量确定性本地向量，资料仍可完成本地入库。

Reranker 使用百炼 `qwen3.7-text-rerank` 的原生 API，与 Embedding 的 OpenAI 兼容接口不同。在模型配置的 Rerank 分类下保存厂商密钥和模型；北京业务空间地址已配置为 `/api/v1` 基础地址。`POST /api/v1/rerank` 接受查询文本、最多 500 条候选文档与可选的 `topN`，返回原始索引、相关性分数和对应文本。对话检索目前使用向量检索与 BM25 的排名融合，尚未自动调用重排接口。

## 知识问答 Agent 工作流

`app/agents/` 是知识问答域的工作流入口。可调用工具集中放在 `app/tools/`，每个工具各占一个文件：`bm25_search.py`、`search_knowledge_base.py`、`web_search.py` 和 `current_datetime.py`。`KnowledgeSupervisor` 通过 `KnowledgeTools` 调用本地知识库检索和按需联网检索，再将证据交给 `KnowledgeAgent`。本地检索融合 Chroma 向量排名与 SQLite 文档分块的 BM25 排名，仅使用当前用户已经向量化完成的资料；已有的文档归属和 PDF 页码校验仍在路由层执行。纯日期、星期和时间问题直接读取服务器的北京时间，不进行 RAG 或联网搜索。

联网搜索使用百度纯搜索接口。`.mindpoilt/models.json` 的 `integrations.baidu_search.authorization` 必须填写完整鉴权字段，格式为 `Bearer bce-v3…`；工具会原样放入 `X-Appbuilder-Authorization` 请求头，不接受裸 Key。未配置、格式错误或服务调用失败时，运行监控会显示具体原因。

普通问答只调用生成 Agent 一次，流式输出回答，不调用反思 Agent，也不进行重试。开启前端「深度思考」后，Supervisor 才让 `ReflectionAgent` 对候选回答的准确性、完整性、安全性和相关性评分；加权分数为 `准确性×0.35 + 完整性×0.25 + 安全性×0.25 + 相关性×0.15`，通过阈值为 `0.8`。低于阈值时将具体修改建议交给生成 Agent，最多重试 3 次。候选稿在评估完成前不会作为最终回答发送；如果四轮仍未达标，返回得分最高的版本。评分和实际尝试次数保存在助手消息的 `workflow` 元数据中。当前只实现知识问答域，后续可在同一结构中加入其他域的 Supervisor 和域路由。

右侧「运行监控」显示本轮输入、Supervisor 调度、RAG 命中片段、联网检索、能力应用、生成、反思和输出。各步骤通过流式 `trace` 事件实时更新，并写入 SQLite 的 `agent_runs` 表；检索原文和工具结果在步骤详情中查看。`GET /api/v1/conversations/{id}/agent-runs/latest` 只返回当前用户该会话最近一次运行记录，重新打开会话时用于恢复监控。新一轮开始时前端清空上一轮轨迹。

联网工具保存真实网页的标题、发布时间、网址及图标，并给网页分配本轮编号。生成 Agent 在使用网页信息的句子后写入 `〔网页1〕` 这类标记；回复消息只保留实际引用的网页元数据。前端将标记显示为带图标的链接标签，悬停可查看标题、时间和自动换行的网址，点击会打开原网页。

进入虚拟空间后自动播放中文介绍语，随后开始聆听，无需唤醒词。回答直接使用流式 LLM 和 TTS，不播放固定衔接语；回复和字幕均使用中文。用户停顿 2 秒后提交语音，麦克风开关不中断播报。

图像生成使用百炼 `qwen-image-3.0-pro` 的 OpenAI 兼容接口。在模型配置的 Image 分类下保存厂商密钥，并确保接口地址、API Key 和模型处于同一地域。登录后可在「知识可视化 → AI 图像生成」输入画面描述、选择尺寸，也可添加 1–3 张参考图片进行编辑。前端调用 `POST /api/v1/images/generate`，密钥仅由后端读取。后端会立即下载厂商返回的临时图片并保存到 `backend/data/generated_images/`，图片元数据按用户存入数据库；`GET /api/v1/images` 可查看记录，`GET /api/v1/images/{id}/file` 可下载，`DELETE /api/v1/images/{id}` 可删除。本入口是独立的创作工具，不会把生成画面登记为已核对的知识产物。

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

在 `frontend` 目录运行 `npm run dev`。前端默认通过 Vite 的 `/api` 代理连接本机后端，接口文档位于 `http://127.0.0.1:8000/docs`。只有显式设置 `VITE_API_BASE_URL=off` 才会使用演示数据；如需自定义后端地址，可在 `.env.local` 中设置 `VITE_API_BASE_URL` 并重启前端。切换至后端模式后，需使用后端账号重新登录，演示账号不会自动迁移。

## 目录

```text
app/
  api/routes/       # HTTP 路由与用户权限校验
  core/             # 配置、密码哈希与 JWT
  db/               # SQLAlchemy 模型和数据库会话
  schemas/          # 请求、响应模型
  main.py           # 应用工厂、CORS 和生命周期
tests/              # 认证、权限和持久化测试
```

## 已实现接口

- `/api/v1/auth/register`、`login`、`refresh`、`logout`、`me`、`change-password`、`sessions`：账号注册登录、资料修改、密码修改、查看和撤销登录会话。
- `/api/v1/conversations`：列出、新建、修改、删除当前用户的会话。
- `/api/v1/conversations/{id}/messages`：列出、追加和删除消息，支持消息元数据。
- `/api/v1/conversations/{id}/reply`：读取当前会话历史，先从当前用户的本地 ChromaDB 召回资料分块，再交给`.mindpoilt/models.json` 中启用的文字模型 生成回复，并保存用户消息、模型回复和引用。
- `/api/v1/embeddings`：调用百炼 `qwen3.7-text-embedding` 返回文本向量，使用 `.mindpoilt/models.json` 中启用的模型、密钥与维度配置。
- `/api/v1/documents`：上传、列出、读取和删除本地资料；上传只保存原文件，点击行内按钮调用 `POST /api/v1/documents/{id}/vectorize` 才启动后台解析、切分和 ChromaDB 向量化。列表接口返回阶段状态、已向量化分块数和错误信息，供前端刷新进度。
- `/api/v1/documents/search`：按当前用户的知识域隔离，在本地 ChromaDB 中检索最相关的知识分块。
- `/api/v1/rerank`：调用百炼 `qwen3.7-text-rerank` 重新排序候选文本，使用 `.mindpoilt/models.json` 中的厂商密钥。

密码采用 Argon2id 哈希。15 分钟的 JWT 访问令牌只保存在前端内存；30 天的随机刷新令牌保存在 HttpOnly、SameSite=Strict Cookie，数据库只存其 SHA-256 摘要。刷新令牌每次使用都会轮换；退出和修改密码会撤销服务端会话。会话和消息查询均按登录用户隔离。
同一用户名连续输错密码 5 次后锁定 5 分钟，登录错误不会透露账号是否存在。

如需自定义存储与安全参数，可设置 `MINDPILOT_DATA_DIR`、`MINDPILOT_DATABASE_URL`、`MINDPILOT_JWT_SECRET`（至少 32 字节）、`MINDPILOT_ALLOWED_ORIGINS`（逗号分隔）及 `MINDPILOT_SECURE_COOKIE=true`（HTTPS 时启用）。默认只允许本地 Vite 来源，服务默认应仅绑定 `127.0.0.1`。

开启后端模式后，主对话的纯文本消息会调用 DeepSeek；API Key 始终只由后端读取。未填写密钥时接口返回中文配置错误，不会生成演示回答。附件与其他模块仍保留演示实现。

语音识别使用百炼 `qwen3-asr-flash-realtime`。在模型配置的 ASR 分类下保存厂商密钥，并设置业务空间对应的 `wss://.../api-ws/v1/realtime` 地址。主对话的麦克风通过需要登录的 `/api/v1/speech/live` WebSocket 在录音时发送 16 kHz 单声道 PCM，语音转文字可显示中间结果；停止录音后按百炼 Manual 模式提交最终结果。语音提问再调用现有文字模型回复。`POST /api/v1/speech/transcribe` 仍可用于已有录音的转写。录音最长 60 秒，麦克风需要浏览器授权。

语音合成使用百炼 `qwen-audio-3.1-tts-flash`。在模型配置的 TTS 分类下保存厂商密钥；接口地址使用同一业务空间的 `wss://.../api-ws/v1/inference`，AI 管家开场、后续回复和文本对话朗读均由模型配置的音色字段指定为 `longanwen_v3.1`，播报语气由 `.mindpoilt/models.json` 中的 `options.instruction` 指定。登录后点击助手回复下方的朗读按钮，会调用 `POST /api/v1/speech/synthesize` 并尽可能边接收 MP3 边播放；点击高亮的暂停图标可暂停，再点击继续。API Key 只由后端读取。
原先浏览器 `localStorage` 里的演示账号与会话不会自动迁移到 SQLite；开启后端模式后请注册新账号。

运行测试：`pip install -r requirements-dev.txt`，然后执行 `python -m pytest -q`。

## 个人资料与使用统计

侧栏「个人资料」可修改显示名称与头像，头像由浏览器居中裁剪为 256×256 的 JPEG 后保存到账号资料。后端启动时自动迁移新增的头像字段，刷新或重新登录仍会保留。

`GET /api/v1/auth/me/statistics` 仅汇总当前账号已保存的会话：记录的输入与输出 Token、单轮峰值、会话数、消息数、回复耗时、功能选择次数、工具调用与连续使用天数。日期按北京时间划分，昨天使用且今天尚未开始时保留连续天数。流式文本请求开启 `include_usage`，模型返回的用量随回复保存；未返回的用量不估算，界面显示缺少用量的回复数。历史已删除的会话不计入此汇总，演示模式明确标示演示数据。





## 海报设计功能域

在聊天输入框选择「海报设计」后，请输入传播目标、指定文案与风格，也可以上传二维码或其他图片。主 Agent 将任务交给海报域；有上传图片时，素材理解 Agent 先把真实图片传给支持视觉输入的模型，取得逐张的主体、可见文字、用途和建议位置。域内主管据此提炼需求，可按需调用联网搜索或文生图工具，再交给视觉设计 Agent 决定品牌标志、主视觉、二维码和辅助图片的位置。浏览器渲染工具输出 HTML、PNG、PDF；图稿质检 Agent 利用截图的尺寸、分区亮度与对比度和文案规则提出可定位的意见，必要时携带问题返回设计 Agent，最多设计三版。运行监控仅记录实际发生的阶段。

海报图片通过 `POST /api/v1/files/poster-assets` 保存在用户隔离的本地预览目录。素材理解时，后端将缩放后的真实图片以图文输入发送给视觉模型；DeepSeek 配置会使用 `deepseek-flash`，无需先上传至 Files API。模型请求日志只记录图片数量和大小，不重复保存 base64。导出的 HTML 内嵌原用户图片。海报域使用本机 Chrome 或 Edge 的无头模式渲染。部署后端时请安装其中一种浏览器，并确保服务进程可启动它；Python 侧 Pillow 依赖已列入 `requirements.txt`。示例见 `examples/poster-preview.html` 和 `examples/poster-preview.png`。

## 首轮会话标题功能域

首轮用户提问与首轮 AI 回复保存成功后，数据库事务中的消息钩子自动创建一条标题任务。任务以会话 ID 为主键，持久化首轮消息的快照；不会读取后续轮次、分支继承上下文或整个历史。事务回滚不会留下任务。无回复、空白会话均不触发。无论任务完成、失败、被拒绝或被手动改名覆盖，后续发消息、刷新或关闭窗口都不会创建第二次任务。普通问答、语音、海报、绘图和地图发送均使用同一个消息事务钩子，不依赖前端离开会话。

主管 Agent 调度标题生成 Agent 与独立 Reflection Agent。标题最多10字符；准确性、核心主题/主要任务覆盖度、相关性、简洁性权重分别为0.4/0.3/0.2/0.1，总分阈值0.85，准确性至少0.8、覆盖度至少0.75。评审的是简短标签，不能要求包含所有文案、亮点和导出格式。主管传递上稿与修改意见，单次工作流最多评审三稿。正常通过仅调用生成和反思各一次。首轮内容异常长时主管才分块压缩首轮数据，之后各稿复用同一份上下文。三稿均失败或模型服务异常时，保留首问作为备用标题，不在后续对话重新尝试。

后台使用独立2线程池，额外任务持久化按创建时间排队。启动时只恢复未完成的排队/运行任务，不重跑终态任务；这是继续原任务，不是新触发。队列适用于当前单进程本地后端。标题更新保留最近活动时间，并通过条件更新保护生成期间的手动改名。`GET /api/v1/conversations/{id}/title-generation` 只读任务状态与标题，按用户隔离，没有重新触发接口。前端在首轮回复完成后轮询结果并同步列表、聊天顶部和地图；聊天顶部仍保留最多10字符加 `...` 的显示限制。标题域隐式运行，不展示内部评分过程；任务记录评审结果和模型用量。
