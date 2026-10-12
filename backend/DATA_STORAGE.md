# 本地数据隔离

项目将 Agent 状态与应用业务数据分开保存。默认布局如下：

```text
MindPilot/
├── .mindpoilt/
│   ├── config.toml                     # 上下文与记忆策略
│   ├── models.json                     # 模型参数、厂商密钥、工具服务凭证
│   ├── state_1.sqlite                  # 会话查询投影、工具任务、事件队列、记忆检查点
│   ├── session_index.jsonl
│   ├── sessions/YYYY/MM/DD/*.jsonl     # 原始会话、工具事件、压缩摘要
│   ├── archived_sessions/
│   ├── memories/<用户ID>/*.md          # 长期记忆及来源摘要
│   ├── thread-writer-locks/
│   ├── backups/                       # 仅 Agent 状态备份
│   └── tmp/
└── backend/data/
    ├── mindpoilt.sqlite               # 账号、登录状态、个人资料、文件与业务索引
    ├── .jwt_secret                    # 用户认证的 JWT 签名密钥
    ├── documents/<用户ID>/            # 上传资料
    ├── chat_previews/<用户ID>/         # 聊天上传文件及预览
    ├── agent_artifacts/               # 工具生成文件
    ├── generated_images/<用户ID>/      # 生成图片
    ├── chroma/                        # 上传资料的向量索引
    ├── speech_cache/asr/              # 为语音识别缓存预留
    ├── speech_cache/tts/              # 为语音合成缓存预留
    ├── model_comparisons/rag/<空间ID>/ # 独立、可过期的 RAG 测试文档
    └── backups/                       # 业务库及历史混合库备份
```

`mindpoilt.sqlite` 的拼写与 `.mindpoilt` 一致。当前语音仍采用流式处理，语音目录不会自动缓存音频。LLM 对比结果留在当前界面；RAG 测试文档、黄金标注及最近三份完成报告在独立临时空间中保存，24 小时未写入后过期。详见 [RAG 评测](RAG_EVALUATION.md)。

## SQLite 表归属

| 数据库 | 表 |
| --- | --- |
| `backend/data/mindpoilt.sqlite` | `users`、`auth_sessions`、`login_attempts`、`documents`、`document_chunks`、`agent_artifacts`、`generated_images`、`workbench_entries`、`evaluation_workspaces`，以及 Alembic 版本表 |
| `.mindpoilt/state_1.sqlite` | `conversations`、`messages`、`conversation_maps`、`conversation_inheritance`、`agent_runs`、`agent_tasks`、`agent_task_events`、`conversation_title_jobs`、`conversation_journals`、`session_events`、`memory_extractions`、`memory_documents`、旧 `model_configurations` 表 |

模型配置的实际来源仍是 `.mindpoilt/models.json`，通过 `app/core/config.py` 校验读取。旧 `model_configurations` 表仅保留历史元数据，不接管模型凭证。JWT 密钥属于用户登录认证，因此留在业务目录；厂商 API Key 属于模型配置，留在 Agent 状态目录。现有 `.env` 保留，模型不从中读取配置。

工具的执行状态、输入输出及上下文引用属于 Agent 状态；工具生成的可下载文件及文件索引属于业务数据。会话记录仍使用原来的 JSONL 追加机制，达到阈值后读取有效压缩摘要加最近十轮完整对话，长期记忆仍为按用户隔离的 Markdown。

## 读取、事务和权限

`storage_layout.py` 集中声明表归属与目录边界。ORM 为 Agent 表添加 `agent_state` schema。每个连接以业务库为主库，并将状态库通过 SQLite `ATTACH` 挂载为 `agent_state`，因此现有查询、统计和同一事务里的更新可以跨库执行。

两个数据库使用磁盘文件和 DELETE 回滚日志，保留跨库事务的一致性；不启用 WAL。JSONL 的待写事件仍与消息投影在同一事务中提交，文件追加失败后仍可重试。

SQLite 不支持跨数据库声明外键：各库内部的外键继续由 SQLite 执行，跨库的 ORM 引用由 `storage_integrity.py` 在提交前验证。删除会话或任务会清理业务库中关联的工具文件元数据。接口继续核验登录与所属用户。直接通过 SQLite 客户端修改跨库引用不会经过 ORM 校验，应使用应用服务操作。

这是存储位置和职责隔离，并不是操作系统权限或独立服务隔离；后端仍需要访问两个目录。备份恢复应同时保存两库、JSONL、记忆文件、模型配置、业务文件和 `.jwt_secret`，以保留彼此的关联及登录有效性。

## 现有数据迁移

启动时先检查是否存在旧混合库：原 `.mindpoilt/state_1.sqlite`、显式指定的旧业务库，或初次安装时的 `backend/data/mindpilot.db`。迁移步骤如下：

1. 持有迁移锁，使用 SQLite backup 保存包含已提交数据的完整备份到 `backend/data/backups/`。
2. 在临时副本上升级旧表结构，创建两个新的数据库，将每张表复制到对应位置。
3. 对比逐表行数和全部列值，执行完整性及外键检查。账号 ID、密码哈希、刷新令牌哈希、文档路径、消息及记忆检查点保持原值。
4. 先持久保存迁移清单和目标文件校验值，再替换两个数据库。若两次替换之间中断，下次启动依据清单继续，不重复导入。
5. 将 `.mindpoilt/backups/` 下包含账号或业务表的旧 SQLite 备份移入 `backend/data/backups/`，避免混合备份继续留在 Agent 状态目录。

当目标库同时已有数据、出现未分类的旧表或校验不一致时，迁移停止，不覆盖现有数据。迁移后不再将业务数据库复制到 `.mindpoilt`。原 JSONL、Markdown、模型配置、JWT 密钥和 `.env` 无需重写。启动前应停止旧版本服务；迁移会在准备副本期间锁住旧库写入。

默认业务数据库由 `load_settings()` 指向 `backend/data/mindpoilt.sqlite`。`MINDPILOT_DATA_DIR` 可指定业务文件目录；`MINDPILOT_DATABASE_URL` 可指定另一个 SQLite 业务库，但必须与状态库使用不同文件。自定义测试数据库使用隔离的状态目录。

新增表必须更新 `STATE_TABLES` 或 `BUSINESS_TABLES`，并通过 `migration_ops.py` 处理迁移；新的模型配置字段仍需经过 `config.py` 校验，不应直接从接口读取配置文件。
