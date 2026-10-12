# 账户与登录信息存储

MindPilot 的默认后端模式使用本地多账户管理；账户所属关系也用于隔离会话、资料和记忆。以下位置已经按当前代码和实际数据库核对。

| 信息 | 保存位置 | 内容与使用方式 |
| --- | --- | --- |
| 用户账户与个人资料 | `backend/data/mindpoilt.sqlite` 的 `users` 表 | 用户 ID、用户名、头像、个人资料、Argon2 密码哈希；不保存明文密码 |
| 登录会话 | 同一数据库的 `auth_sessions` 表 | 用户 ID、刷新令牌的 SHA-256 哈希、创建和到期时间、记住登录、撤销状态；不保存原始刷新令牌 |
| 登录失败与临时锁定 | 同一数据库的 `login_attempts` 表 | 失败次数和锁定截止时间；连续五次失败后临时锁定五分钟 |
| JWT 签名密钥 | `backend/data/.jwt_secret` | 服务端 HS256 签名密钥，默认首次生成并持久保存；可通过 `MINDPILOT_JWT_SECRET` 显式提供 |
| 访问令牌 | 浏览器的 Pinia 与 HTTP 模块内存 | 默认有效十五分钟；后端模式不会将其写入 localStorage |
| 刷新令牌 | 浏览器 `mindpilot_refresh` Cookie | HttpOnly、SameSite=Strict、路径 `/api/v1/auth`；勾选记住登录时默认持久三十天，否则为会话 Cookie；Secure 由部署设置控制 |
| 模型及工具服务凭证 | `.mindpoilt/models.json` | 厂商 API Key、语音凭证、搜索鉴权与模型参数，由 `config.py` 校验后读取；与用户登录身份分开 |

刷新时后端检查 SQLite 中的登录状态，将刷新令牌轮换为新值，并签发新的访问令牌。每次受保护请求同时检查 JWT 和对应登录会话；退出或修改密码会撤销相应会话。页面刷新后通过 Cookie 调用 `/auth/refresh` 恢复登录。

`frontend/src/stores/auth.js` 同时包含离线演示分支。只有显式设置 `VITE_API_BASE_URL=off` 时，演示账户和演示登录状态才写入 localStorage 的 `mindpilot-users` 和 `mindpilot-session`。演示密码是明文，演示令牌没有后端权限；默认后端模式不使用这些数据进行认证。

## Codex 对照

依据 [OpenAI 官方认证文档](https://learn.chatgpt.com/docs/auth)，Codex CLI 与 IDE 扩展可复用本地缓存的外部登录凭证。`cli_auth_credentials_store` 支持 `file`、`keyring`、`auto`、`ephemeral`：分别使用 `CODEX_HOME/auth.json`、操作系统凭据库、优先凭据库并回退文件、仅当前进程内存。ChatGPT 登录的令牌会在使用中自动刷新。

本机 `C:/Users/YOUR_USERNAME/.codex/auth.json` 存在，`auth_mode` 为 `chatgpt`。检查只输出了字段名：顶层含 `OPENAI_API_KEY`、`auth_mode`、`tokens`、`last_refresh`，`tokens` 含 `id_token`、`access_token`、`refresh_token`、`account_id`。没有输出或复制任何令牌值。本机 `config.toml` 没有显式设置 `cli_auth_credentials_store`，因此不能仅凭该字段判断所有客户端实际采用的存储方式。

Codex 的这种文件是 OpenAI 登录凭证缓存。MindPilot 则自行验证本地用户密码、管理多个账户和会话撤销，需要 SQLite 中的账户和会话记录。账号与登录信息已迁移到业务目录，密码哈希、登录状态及 JWT 密钥保持原值；不会将用户密码或浏览器令牌导出到 `auth.json`。完整目录及迁移说明见 [本地数据隔离](DATA_STORAGE.md)。
