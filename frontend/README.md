# MindPilot 前端

MindPilot 是**本地个人知识助手**：把本地资料导入并建立索引，用于知识管理、知识查询（带引用来源的问答）与知识可视化生成。产品与模块划分以仓库根目录的 `MindPilot-项目设计.md` 为准。

本目录是 MindPilot 前端。默认通过同源 `/api` 代理连接仓库中的 FastAPI 后端；登录注册、会话记录与模型配置使用后端。显式设置 `VITE_API_BASE_URL=off` 时才使用演示账号与会话数据。

## 页面

| 路由 | 页面 | 说明 |
| --- | --- | --- |
| `/login` | 登录 | 后端模式使用 JWT 与刷新会话；演示模式使用本地账号 |
| `/register` | 注册 | 后端模式写入 SQLite；演示模式写入浏览器本地账号表 |
| `/` | 对话助手 | 带引用来源的知识问答 |
| `/documents` | 知识资料 | 文档导入、切分、检索与向量化 |
| `/wiki` | LLM Wiki | 主题页 / 概念页 / 论文页 / 对比页 |
| `/visualization` | 知识可视化 | 知识图谱与图谱版式切换 |
| `/memory` | 记忆管理 | 工作记忆 / 情景记忆 / 长期记忆 |
| `/grants` | 授权中心 | 工具池授权、知识域隔离与外发检查 |
| `/traces` | 运行面板 | 执行链路、token 与成本核算 |
| `/model-config` | 模型配置 | LLM / Embedding / 向量库 / 检索 / ASR / TTS 等 |

## 已实现

- 登录、注册、表单校验、路由守卫；可选 FastAPI 认证与会话持久化
- 对话助手：会话搜索/新建/重命名/置顶/删除、文件附件、模拟流式回复、消息操作、引用来源展开
- 知识资料：筛选、表格/卡片视图切换、导入、预览、切分与向量化、删除
- LLM Wiki：页面类型分组、编译进度、页面详情与关联引用
- 知识可视化：知识图谱渲染、版式与筛选切换
- 记忆管理：三层记忆分层展示、记忆条目增删改、来源溯源
- 授权中心：授权列表与状态、工具池与知识域选择、外发检查（egress 预演）
- 运行面板：执行链路时间线、token 与成本统计
- 模型配置：各类模型与检索组件配置、连接测试模拟
- Toast、确认弹窗、Loading、空状态与页面过渡；桌面、平板、手机响应式布局

## 技术栈

Vue 3（Composition API + `<script setup>`）、JavaScript、Vite、Vue Router、Pinia、Lucide Vue Next、原生 CSS。

项目严格使用 JavaScript 与 Vue 单文件组件，**不含 TypeScript**。

`axios` 用于后端模式的 HTTP 接口访问。

## 本地运行

```bash
npm install
npm run dev
```

默认地址 `http://localhost:5173`。使用后端时请先注册账号；演示模式可使用 `demo / 123456`。接入后端的方法见 [后端说明](../backend/README.md)。

## 构建

```bash
npm run build            # Web 构建，base 为 /
npm run build -- --mode desktop   # 桌面构建，base 为 ./，路由改用 hash 模式
npm run preview
```

两种模式共用同一套页面代码，差异只在 `vite.config.js` 的 `base` 与 `src/router/index.js` 的历史模式选择。

## 目录结构

```text
src/
├── api/index.js   # 演示数据与后端会话接口适配
├── api/http.js    # 后端请求、访问令牌及刷新逻辑
├── components/    # 品牌标识、页面框架、聊天消息、弹窗等
├── mock/          # 演示数据与本地持久化
├── router/        # 路由与前端鉴权守卫
├── stores/        # Pinia 状态（auth 会话、chat、ui、app）
├── styles/        # 全局视觉系统与响应式样式
└── views/         # 10 个页面
public/favicon.svg # 与应用内 .logo-mark 同一枚图标
```

## 接入后端

启动 FastAPI 后运行 Vite 即可。开发服务器把同源 `/api` 请求代理到 `127.0.0.1:8000`，从而正确使用 HttpOnly、SameSite Cookie。登录、注册、账户资料、会话记录和模型配置使用后端；知识资料和正式模型调用仍为演示数据。部署或桌面打包时需另行提供同源 `/api` 代理。

## 安全约定

- **API Key 等凭据不得写入仓库、普通审计日志或模型上下文。** 模型配置页通过后端把 API Key 写入本机私有 `.env` 文件，普通配置响应不返回密钥明文。
- 显式设置 `VITE_API_BASE_URL=off` 时不发起后端请求，演示账号与会话保存在浏览器本地。
- 启用后端时访问令牌仅留在内存，刷新令牌由后端设置为 HttpOnly Cookie；演示用的 `mindpilot-session` 不参与后端鉴权。
