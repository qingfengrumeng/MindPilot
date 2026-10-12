"""LangGraph supervisor: plan from compact capability summaries, dispatch, inspect, repeat."""

from __future__ import annotations

import json
from time import monotonic
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.runtime.agent_runner import RunContext
from app.runtime.protocol import TaskResult, TaskSpec
from app.services.text_generation import complete_text
from app.tools.current_datetime import is_current_datetime_question


class SupervisorState(TypedDict, total=False):
    plan: list[dict]
    cursor: int
    artifact_ids: list[str]
    source_ids: list[str]
    child_task_ids: list[str]
    latest_result: dict
    status: str
    error: str | None
    result: dict


def _intent_plan(spec: TaskSpec) -> list[dict]:
    explicit = spec.inputs.get("steps")
    if explicit is not None:
        if not isinstance(explicit, list) or not 1 <= len(explicit) <= 8:
            raise ValueError("steps must contain 1 to 8 agent intents")
        return [{"intent": str(item.get("intent") or item.get("agent")),
                 "agent": item.get("agent"), "inputs": item.get("inputs") or {}}
                if isinstance(item, dict) else {"intent": str(item), "inputs": {}}
                for item in explicit]
    goal = spec.goal.lower()
    if "海报" in goal or "poster" in goal:
        return [{"intent": "poster", "inputs": {}}]
    if is_current_datetime_question(spec.goal):
        return [{"intent": "knowledge_qa", "inputs": {}}]
    intents = []
    if any(word in goal for word in ("调研", "研究报告", "论文", "literature")):
        intents.append("research_report")
    elif any(word in goal for word in ("知识库", "资料", "检索", "rag")):
        intents.append("knowledge_qa")
    if "思维导图" in goal or "mindmap" in goal:
        intents.append("mindmap")
    elif "流程图" in goal or "架构图" in goal or "diagram" in goal:
        intents.append("flowchart")
    if "ppt" in goal or "演示文稿" in goal or "幻灯片" in goal:
        intents.append("presentation")
    if "markdown" in goal or "排版成 md" in goal or "整理成 md" in goal:
        intents.append("markdown_formatting")
    return [{"intent": intent, "inputs": {}} for intent in intents]


def _model_intent_plan(spec: TaskSpec, runner, user_id: str,
                       conversation_id: str | None) -> list[dict]:
    """Consult compact capability summaries when fixed, obvious intents do not match."""
    catalog = runner.registry.summaries()
    allowed = {intent for manifest in catalog for intent in manifest["intents"]}
    allowed.update(item["id"] for item in runner.skills.summaries())
    context = RunContext(spec.task_id, user_id, conversation_id, runner.settings,
                         runner.session_factory, runner.manager, runner.artifacts,
                         runner.tools, set(), monotonic() + runner.timeout_seconds,
                         runner.max_steps, model_gateway=runner.model_gateway)
    response, _ = context.model([
        {"role": "system", "content": (
            "你是任务路由器。仅根据已安装能力摘要选择 1 到 8 个顺序执行的 intent。"
            "只输出 JSON：{\"steps\":[{\"intent\":\"能力名\"}]}。"
            "不要发明未安装的能力；需要多步时按依赖顺序排列。"
            "只做简单问答时选 knowledge_qa。")},
        {"role": "user", "content": json.dumps({"goal": spec.goal,
                                                  "capabilities": catalog,
                                                  "skills": runner.skills.summaries()},
                                                 ensure_ascii=False)},
    ], purpose="supervisor_planning", complete_fn=complete_text)
    try:
        raw = json.loads(response.strip())
        steps = raw["steps"]
        if not isinstance(steps, list) or not 1 <= len(steps) <= 8:
            raise ValueError("Planner must return 1 to 8 steps")
        parsed = []
        for item in steps:
            intent = item.get("intent") if isinstance(item, dict) else None
            agent = item.get("agent") if isinstance(item, dict) else None
            if intent not in allowed or (agent and agent not in {row["id"] for row in catalog}):
                raise ValueError(f"Planner selected unavailable capability: {intent}")
            parsed.append({"intent": intent, "agent": agent, "inputs": {}})
        return parsed
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"主 Agent 无法从已注册能力中形成有效计划：{exc}") from exc


def _run_markdown(spec: TaskSpec, runner, user_id: str, conversation_id: str | None,
                  artifact_ids: list[str], source_ids: list[str]) -> TaskResult:
    if spec.constraints.get("output_format") not in {None, "markdown", "md"}:
        return TaskResult(status="waiting", error="Markdown Skill 不支持所需输出格式")
    if spec.constraints.get("must_cite_sources") and not source_ids:
        return TaskResult(status="waiting", error="Markdown 文档缺少可核查的来源资料")
    if "markdown_formatting" not in {item["id"] for item in runner.skills.summaries()}:
        return TaskResult(status="waiting", error="Markdown formatting skill is not installed")
    context = RunContext(spec.task_id, user_id, conversation_id, runner.settings,
                         runner.session_factory, runner.manager, runner.artifacts,
                         runner.tools, {"read_artifact", "write_markdown"},
                         monotonic() + runner.timeout_seconds, runner.max_steps)
    instruction = runner.skills.load("markdown_formatting")
    content = str(spec.inputs.get("content") or spec.goal)
    for artifact_id in artifact_ids:
        material = context.tool("read_artifact", {"artifact_id": artifact_id})
        content += "\n\n" + material["content"]
    text, _ = context.model([
        {"role": "system", "content": instruction + "\n只输出最终 Markdown 正文，不要使用包裹全文的代码围栏。"},
        {"role": "user", "content": content[:30000]},
    ], purpose="markdown_formatting", complete_fn=complete_text)
    text = text.strip()
    if not text:
        raise ValueError("Markdown skill returned empty content")
    context.check_active()
    written = context.tool("write_markdown", {"content": text, "filename": "document.md",
                                              "source_ids": source_ids})
    return TaskResult(status="completed", summary="已生成 Markdown 文档",
                      artifact_ids=[written["artifact_id"]], source_ids=source_ids)


def run_supervisor(spec: TaskSpec, runner) -> TaskResult:
    _, user_id, conversation_id = runner.manager.spec(spec.task_id)

    def plan(state: SupervisorState):
        steps = _intent_plan(spec) or _model_intent_plan(spec, runner, user_id, conversation_id)
        step_summary = [{"intent": step["intent"], "agent": step.get("agent"),
                         "input_keys": sorted(step.get("inputs", {}))} for step in steps]
        runner.manager.event(spec.task_id, "plan", {"steps": step_summary,
                                                    "capabilities": runner.registry.summaries()})
        return {"plan": steps, "cursor": 0, "artifact_ids": [], "source_ids": [],
                "child_task_ids": [], "status": "running"}

    def dispatch(state: SupervisorState):
        step = state["plan"][state["cursor"]]
        intent = step["intent"]
        runner.manager.event(spec.task_id, "dispatch_start", {
            "intent": intent, "step_index": state["cursor"],
        })
        if intent == "markdown_formatting":
            result = _run_markdown(spec, runner, user_id, conversation_id,
                                   state["artifact_ids"], state["source_ids"])
            return {"latest_result": result.model_dump(mode="json")}
        agent_id = step.get("agent")
        if agent_id:
            try:
                manifest = runner.registry.get(agent_id)
            except KeyError:
                return {"latest_result": TaskResult(status="waiting", error=f"未安装 Agent：{agent_id}").model_dump()}
            if intent not in manifest.intents and intent != agent_id:
                return {"latest_result": TaskResult(status="waiting", error=f"{agent_id} 不支持 {intent}").model_dump()}
        else:
            candidates = runner.registry.candidates(intent)
            if len(candidates) != 1:
                reason = f"没有安装支持 {intent} 的 Agent" if not candidates else f"多个 Agent 支持 {intent}，需要指定一个"
                return {"latest_result": TaskResult(status="waiting", error=reason).model_dump()}
            agent_id = candidates[0].id
        inputs = {**step.get("inputs", {})}
        inputs.setdefault("query", spec.goal)
        inputs["_step_index"] = state["cursor"]
        if intent in {"flowchart", "mindmap"}:
            inputs.setdefault("kind", intent)
        if intent == "poster":
            for key in ("image_preview_ids", "image_names"):
                if key in spec.inputs:
                    inputs.setdefault(key, spec.inputs[key])
        if state["artifact_ids"]:
            inputs.setdefault("artifact_ids", state["artifact_ids"])
        if state["source_ids"]:
            inputs.setdefault("source_ids", state["source_ids"])
        for existing in runner.manager.children(spec.task_id, user_id=user_id):
            if existing.agent != agent_id or existing.status != "completed" or not existing.result:
                continue
            existing_spec, _, _ = runner.manager.spec(existing.task_id)
            if existing_spec.inputs.get("_step_index") == state["cursor"]:
                runner.manager.event(spec.task_id, "reuse_child", {"child_task_id": existing.task_id,
                                                                   "step_index": state["cursor"]})
                return {"latest_result": existing.result.model_dump(mode="json"),
                        "child_task_ids": [*state["child_task_ids"], existing.task_id]}
        child = runner.run_child(spec, agent=agent_id, goal=spec.goal, inputs=inputs,
                                 user_id=user_id, conversation_id=conversation_id,
                                 constraints=spec.constraints)
        return {"latest_result": child.result.model_dump(mode="json") if child.result else
                TaskResult(status="waiting", error="Child task is queued").model_dump(),
                "child_task_ids": [*state["child_task_ids"], child.task_id]}

    def assess(state: SupervisorState):
        result = TaskResult.model_validate(state["latest_result"])
        runner.manager.event(spec.task_id, "child_result", {"status": result.status,
                                                            "artifact_ids": result.artifact_ids,
                                                            "source_ids": result.source_ids,
                                                            "error": result.error})
        if result.status != "completed":
            return {"status": result.status, "error": result.error}
        return {"cursor": state["cursor"] + 1,
                "artifact_ids": list(dict.fromkeys([*state["artifact_ids"], *result.artifact_ids])),
                "source_ids": list(dict.fromkeys([*state["source_ids"], *result.source_ids]))}

    def route(state: SupervisorState):
        return "finish" if state.get("status") != "running" or state["cursor"] >= len(state["plan"]) else "dispatch"

    def finish(state: SupervisorState):
        status = state.get("status", "completed")
        if status == "running":
            status = "completed"
        latest = TaskResult.model_validate(state["latest_result"]) if state.get("latest_result") else None
        result = TaskResult(status=status, summary=latest.summary if latest else "",
                            artifact_ids=state["artifact_ids"], source_ids=state["source_ids"],
                            outputs={"child_task_ids": state["child_task_ids"],
                                     "completed_steps": state["cursor"]}, error=state.get("error"))
        return {"result": result.model_dump(mode="json")}

    graph = StateGraph(SupervisorState)
    graph.add_node("plan", plan)
    graph.add_node("dispatch", dispatch)
    graph.add_node("assess", assess)
    graph.add_node("finish", finish)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "dispatch")
    graph.add_edge("dispatch", "assess")
    graph.add_conditional_edges("assess", route, {"dispatch": "dispatch", "finish": "finish"})
    graph.add_edge("finish", END)
    final = graph.compile().invoke({}, {"recursion_limit": runner.max_steps * 4})
    return TaskResult.model_validate(final["result"])
