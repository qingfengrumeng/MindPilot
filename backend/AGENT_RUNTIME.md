# Agent 运行平台

运行平台位于 `app/runtime/`，主 Agent 位于 `app/agents/supervisor.py`，专业 Agent 安装在 `app/plugins/<id>/`。知识问答、绘图、科研报告和海报设计是当前已安装的插件；Markdown 排版是 `app/skills/markdown_formatting/SKILL.md`，由主 Agent 直接加载。PPT 插件尚未安装，相关意图会进入 `waiting` 状态，绝不会伪造产物。

## 任务协议

`POST /api/v1/agent-tasks` 接收统一的任务规格。`agent` 可以是 `supervisor` 或某个已安装的插件 ID。用户身份从登录令牌获取；`conversation_id` 可选，存在时必须属于当前用户。默认等待任务结束；传 `"wait": false` 会立即返回任务 ID，后续可查询或取消。

```json
{
  "agent": "supervisor",
  "goal": "根据资料画一张 RAG 流程图",
  "conversation_id": "<conversation-id>",
  "inputs": {
    "steps": ["knowledge_qa", "flowchart"],
    "query": "RAG 的流程"
  },
  "constraints": {"must_cite_sources": true}
}
```

主任务用 LangGraph 的 `plan → dispatch → assess → finish` 工作流执行。`dispatch` 为每个专业 Agent 创建有 `parent_task_id` 的子任务，将上游 `artifact_ids`、`source_ids` 传给下游。子 Agent 返回 `status`、`summary`、`artifact_ids`、`source_ids`、`outputs` 与 `error`。正常单轮图表聊天也通过这个平台执行，同时保留现有的会话消息与运行监控接口。

用户显式给出 `inputs.steps` 时按指定顺序执行；日期时间和常见知识问答、科研、绘图、PPT、Markdown 请求由轻量规则直达。未匹配明显意图时，主 Agent 只把已注册插件与 Skill 的能力摘要交给模型规划，再校验每个 intent 确实存在；完整插件提示词不会提前塞进规划上下文。模型规划结果也经 `ModelGateway` 记录。显式或规则计划需要未安装的插件时，任务进入 `waiting`；模型若返回未注册的能力，计划校验失败，不会生成假产物。

专业 Agent 由 `app/runtime/agent_loop.py` 的共用循环执行。插件可以 `yield ToolCall(...)` 或 `ModelCall(...)`，循环负责步骤上限、执行、状态和记录；领域决策留在插件内。直接调用模型的旧逻辑也须经 `context.model(...)`，其模型请求与响应由 `ModelGateway` 统一记录。`ModelGateway` 是可注入的模型适配边界，后续更换模型供应商不必改插件。工具调用只通过 `context.tool(...)` 或 `ToolCall`，参数由 Pydantic 校验，并按插件清单中的白名单限制。

状态包括 `queued`、`running`、`waiting`、`completed`、`failed` 和 `cancelled`。当前每个运行器最多同时执行 4 个专业任务，单次专业任务的等待上限为 120 秒，工具/Agent 步骤上限为 24。取消与超时采用协作式检查；外部请求无法被强制终止，但任务返回后不能将已取消任务改为完成。服务重启会把仍在运行的任务变为可重试的 `waiting`。重试主任务时复用已经完成的子任务和产物。

任务、步骤事件和产物元数据分别存在 `agent_tasks`、`agent_task_events`、`agent_artifacts` SQL 表中。文件在服务器数据目录的 `agent_artifacts/<user-id>/` 下，任务之间只传产物 ID。用户只能读取自己的任务和产物。大段工具参数只在日志中保存长度摘要。

运行记录包含 `turn_start/end`、`step_start/end`、`model_request/response/attempt`、`tool_call/result` 和 `artifact_saved`。每个模型请求的实际消息及对应回复另存为用户私有产物，事件只保存其 ID、模型、耗时和 token 元数据；工具结果保存类型、长度、摘要哈希和来源/产物 ID，不复制整份搜索结果或 XML。失败的模型调用只写 `model_attempt`，不会写成功的 `model_response`。`GET /api/v1/agent-tasks/{id}/trace` 将主任务与所有子任务的事件合成一条时间线。

## 安装一个专业 Agent

1. 在 `app/plugins/<id>/` 建立 Python 包和 `manifest.yaml`。
2. Manifest 声明 `id`、语义版本、简短说明、`intents`、输入/输出字段、`required_tools`、`entrypoint` 与 `input_schema`。
3. 在同一个入口模块中定义 Pydantic 输入模型和 `run(task_spec, context) -> TaskResult`。多步插件可将 `run` 写成生成器，`yield ToolCall` / `ModelCall`，最后 `return TaskResult`；Agent 通过 `context.artifacts` 保存大产物。
4. 启动或重试任务时扫描插件目录，检查版本、入口函数、输入模型和工具依赖。注册只读取清单与代码结构；入口模块在选中后才导入。

例如 `app/plugins/diagram_agent/manifest.yaml`。Manifest 中的意图是能力路由依据。若没有匹配插件或多个插件声明同一意图而用户未指定，主任务进入 `waiting`，不会猜测。

工具统一注册在 `app/tools/runtime_tools.py`。注册时给每个工具指定 Pydantic 参数模型，运行时只允许调用当前插件 manifest 的 `required_tools`。Skill 目录仅提供简要说明和按需加载的完整指令；Markdown 文件由 `write_markdown` 工具保存。

## 接口

- `GET /api/v1/agent-modules`：仅返回能力摘要与 Skill 摘要。
- `GET /api/v1/agent-modules/{id}`：查看选定插件的完整清单和输入 JSON Schema。
- `POST /api/v1/agent-tasks`：创建并执行任务。
- `GET /api/v1/agent-tasks/{id}`：状态、事件与子任务。
- `GET /api/v1/agent-tasks/{id}/trace`：主任务及全部子任务的统一事件时间线。
- `POST /api/v1/agent-tasks/{id}/cancel`、`/retry`、`/run`：取消、重试或运行排队任务。
- `GET /api/v1/agent-tasks/{id}/artifacts`：列出任务及直接子任务的产物版本。
- `GET /api/v1/agent-artifacts/{id}`：下载当前用户的产物。

现有知识问答流式聊天继续保留原有事件接口，以维持逐字输出与运行监控；它和新任务入口复用同一知识生成、反思与检索实现。后续迁移流式入口时需要把 token 事件接入运行平台，不应牺牲现有实时体验。

## 内置绘图子链路

绘图目前是产品内置功能，由主 Agent 调用 `diagram_agent` 子链路；第三方 Agent 安装和卸载仍是后续扩展。新图表依次经过 `drawing_content`（梳理节点、分支、关系）、`drawing_layout`（决定节点顺序和分层）和 `diagram_render`（校验并生成 draw.io XML 与 SVG 预览）。前两步有独立模型请求和运行事件，校验失败时各允许一次纠正。修改已有图表时沿用其 XML 和元素 ID，只进行精确编辑，避免重绘使手动调整丢失。

编辑工作台通过 `POST /api/v1/conversations/{conversation_id}/messages/{message_id}/diagram/turns` 提交当前画布 XML、用户指令和版本号。每轮从当前 XML 生成新版本，并把编辑对话与产物 ID 保存在原图表消息中；重新打开仍可接着修改。手动保存接口也接受 `baseVersion`，旧版本提交会返回 409，防止覆盖新图稿。前端从 `frontend/vendor/drawio` 提供本地定制的 draw.io 编辑器，通过 embed JSON 协议装载和导出 XML；源码中的 `mindpilot=1` 模式仅显示画布，外层工作台负责对话与保存。
