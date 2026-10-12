"""LangGraph drawing domain: specialist agents share a small, explicit state."""

from __future__ import annotations

from functools import lru_cache
import json
from typing import Any, TypedDict
from xml.etree.ElementTree import ParseError

from langgraph.graph import END, START, StateGraph

from app.agents.drawing_content import content_messages, parse_content
from app.agents.drawing_layout import apply_layout, layout_messages
from app.agents.drawing_review import parse_review, review_messages
from app.runtime.protocol import TaskResult, TaskSpec
from app.services.text_generation import TextGenerationError
from app.skills import ai_drawing
from app.skills.drawing_engine import DiagramError
from app.skills.drawing_profiles import DrawingProfile, load_drawing_profile
from app.skills.drawing_preview import render_preview

from .review import inspect_diagram


class DrawingState(TypedDict, total=False):
    context: Any
    spec: TaskSpec
    prompt: str
    kind: str
    profile: DrawingProfile
    next_agent: str
    handoff_context: dict
    source_ids: list[str]
    previous_xml: str | None
    base_plan: dict
    plan: dict
    layout_mode: str
    layout_attempts: int
    feedback: str
    result: dict
    preview: str
    review: dict
    review_history: list[dict]
    layout_retry_failed: bool
    fallback_reason: str
    final_result: TaskResult


def _handoff(state: DrawingState, agent: str, stage: str) -> None:
    state["context"].check_active()
    state["context"].event("drawing_agent_handoff", {
        "agent": agent, "stage": stage,
        "layout_attempt": state.get("layout_attempts", 0),
    })


def _domain_supervisor(state: DrawingState) -> dict:
    """Choose the domain route and pass profile plus review feedback to specialists."""
    context = state["context"]
    context.check_active()
    attempt = state.get("layout_attempts", 0) + (0 if state.get("previous_xml") else 1)
    context.event("drawing_stage", {"stage": "domain_supervisor", "status": "running",
                                    "attempt": attempt})
    profile = load_drawing_profile(state["kind"])
    next_agent = "edit_agent" if state.get("previous_xml") else "content_agent"
    handoff_context = {
        "profile": profile.id,
        "task_goal": state["prompt"][:1000],
        "attempt": attempt,
        "review_feedback": state.get("feedback", "")[:5000],
        "previous_version": bool(state.get("previous_xml")),
    }
    context.event("drawing_stage", {"stage": "domain_supervisor", "status": "completed",
                                    "attempt": attempt, "profile": profile.id,
                                    "next_agent": next_agent,
                                    "has_review_feedback": bool(state.get("feedback"))})
    return {"profile": profile, "next_agent": next_agent,
            "handoff_context": handoff_context}


def _content_agent(state: DrawingState) -> dict:
    _handoff(state, "content_agent", "content_planning")
    context = state["context"]
    number = state.get("layout_attempts", 0) + 1
    context.event("drawing_stage", {"stage": "content_planning", "status": "running",
                                    "attempt": number})
    messages = content_messages(state["prompt"], state["kind"],
                                state.get("handoff_context", {}).get("review_feedback", ""),
                                state.get("base_plan"), state["profile"])
    for attempt in range(2):
        try:
            raw, _ = context.model(messages, purpose="drawing_content",
                                   complete_fn=ai_drawing.complete_text)
        except TextGenerationError as exc:
            if (state.get("result") and state.get("preview") and state.get("review")
                    and not state["review"]["hard_issues"]):
                context.event("drawing_content_fallback", {"attempt": number,
                                                           "reason": str(exc)[:200]})
                return {"layout_retry_failed": True, "fallback_reason": str(exc)}
            raise
        try:
            plan = parse_content(raw, state["kind"])
            break
        except DiagramError as exc:
            if attempt:
                raise
            messages.extend([
                {"role": "assistant", "content": raw[:12000]},
                {"role": "user", "content": f"内容规划未通过校验：{exc}。请修正并只返回完整 JSON。"},
            ])
    context.event("drawing_stage", {"stage": "content_planning", "status": "completed",
                                    "attempt": number, "nodes": len(plan["nodes"]),
                                    "edges": len(plan["edges"])})
    return {"base_plan": plan, "plan": plan}


def _layout_agent(state: DrawingState) -> dict:
    _handoff(state, "layout_agent", "layout_design")
    context = state["context"]
    number = state.get("layout_attempts", 0) + 1
    context.event("drawing_stage", {"stage": "layout_design", "status": "running",
                                    "attempt": number})
    messages = layout_messages(state["base_plan"], state["kind"],
                               state.get("handoff_context", {}).get("review_feedback", ""),
                               state["profile"])
    for attempt in range(2):
        try:
            raw, _ = context.model(messages, purpose="drawing_layout",
                                   complete_fn=ai_drawing.complete_text)
        except TextGenerationError as exc:
            context.event("drawing_layout_fallback", {"attempt": number,
                                                       "reason": str(exc)[:200],
                                                       "using_previous_draft": bool(state.get("result"))})
            if (state.get("result") and state.get("preview") and state.get("review")
                    and not state["review"]["hard_issues"]):
                return {"layout_attempts": number, "layout_retry_failed": True,
                        "fallback_reason": str(exc)}
            plan, mode = apply_layout("{}", state["base_plan"], state["kind"])
            break
        try:
            plan, mode = apply_layout(raw, state["base_plan"], state["kind"])
            break
        except DiagramError as exc:
            if attempt:
                raise
            messages.extend([
                {"role": "assistant", "content": raw[:12000]},
                {"role": "user", "content": f"排版方案未通过校验：{exc}。保持原图内容，修正后只返回 JSON。"},
            ])
    context.event("drawing_stage", {"stage": "layout_design", "status": "completed",
                                    "layout_mode": mode, "attempt": number})
    return {"plan": plan, "layout_mode": mode, "layout_attempts": number,
            "layout_retry_failed": False}


def _render_agent(state: DrawingState) -> dict:
    _handoff(state, "render_agent", "diagram_generation")
    context = state["context"]
    context.event("drawing_stage", {"stage": "diagram_generation", "status": "running",
                                    "attempt": state.get("layout_attempts", 0)})
    result = context.tool("diagram_render", {
        "prompt": state["prompt"][:12000], "kind": state["kind"],
        "plan": state["plan"], "layout_mode": state["layout_mode"],
    })
    context.event("drawing_stage", {"stage": "diagram_generation", "status": "completed",
                                    "attempt": state.get("layout_attempts", 0),
                                    "nodes": result["nodes"], "edges": result["edges"]})
    return {"result": result}


def _edit_agent(state: DrawingState) -> dict:
    _handoff(state, "edit_agent", "precise_edit")
    context = state["context"]
    context.event("drawing_stage", {"stage": "precise_edit", "status": "running"})
    result = context.tool("diagram_render", {
        "prompt": state["prompt"][:12000], "kind": state["kind"],
        "previous_xml": state["previous_xml"],
        "editor_history": state["spec"].inputs.get("editor_history", []),
    })
    context.event("drawing_stage", {"stage": "precise_edit", "status": "completed",
                                    "operations": len(result.get("operations", []))})
    return {"result": result}


def _review_agent(state: DrawingState) -> dict:
    _handoff(state, "review_agent", "diagram_review")
    context = state["context"]
    context.event("drawing_stage", {"stage": "diagram_review", "status": "running",
                                    "attempt": state.get("layout_attempts", 0)})
    try:
        preview = render_preview(state["result"]["xml"])
        review = inspect_diagram(state["result"]["xml"], preview,
                                 plan=state.get("plan") if not state.get("previous_xml") else None,
                                 editing=bool(state.get("previous_xml")),
                                 kind=state["profile"].id)
    except (DiagramError, ValueError, ParseError) as exc:
        preview = ""
        review = {"approved": False, "hard_issues": [str(exc)], "layout_issues": [],
                  "findings": [], "width": 0, "height": 0}
    for problem in review["hard_issues"]:
        review["findings"].append({
            "problem": problem,
            "suggestion": "重新核对节点、连线和画布结构，生成完整且可编辑的图稿",
        })
    if not state.get("previous_xml") and not review["hard_issues"]:
        try:
            raw, _ = context.model(
                review_messages(state["prompt"], state["result"]["xml"],
                                state["kind"], review, state["profile"]),
                purpose="drawing_review", complete_fn=ai_drawing.complete_text)
            decision = parse_review(raw)
            if decision is None:
                context.event("drawing_review_fallback", {"reason": "invalid_review_response"})
            elif not decision[0]:
                finding = {"problem": decision[1], "suggestion": decision[2]}
                review["findings"].append(finding)
                review["layout_issues"].append(
                    f"{finding['problem']}；修改建议：{finding['suggestion']}")
                review["approved"] = False
        except Exception as exc:
            context.event("drawing_review_fallback", {"reason": str(exc)[:200]})
    history = [*state.get("review_history", []), {
        "attempt": state.get("layout_attempts", 0),
        "layout_mode": state.get("layout_mode"),
        "node_order": [node["id"] for node in state.get("plan", {}).get("nodes", [])],
        "findings": review["findings"],
    }]
    context.event("drawing_stage", {"stage": "diagram_review",
                                    "status": "completed" if review["approved"] else "needs_revision",
                                    "attempt": state.get("layout_attempts", 0),
                                    "issues": review["hard_issues"] + review["layout_issues"],
                                    "findings": review["findings"],
                                    "canvas": {"width": review["width"],
                                               "height": review["height"]}})
    return {"preview": preview, "review": review, "review_history": history,
            "feedback": json.dumps({"latest_review": history[-1],
                                    "previous_reviews": history[:-1][-2:]},
                                   ensure_ascii=False)}


def _after_review(state: DrawingState) -> str:
    review = state["review"]
    max_retries = state["profile"].max_retries
    if (not state.get("previous_xml") and (review["hard_issues"] or review["layout_issues"])
            and state.get("layout_attempts", 0) <= max_retries):
        state["context"].event("drawing_relayout", {
            "retry": state["layout_attempts"], "max_retries": max_retries,
            "findings": review["findings"],
        })
        return "domain_supervisor"
    if (not state.get("previous_xml") and (review["hard_issues"] or review["layout_issues"])):
        state["context"].event("drawing_review_exhausted", {
            "retries": max_retries, "findings": review["findings"],
        })
    return "publish"


def _publish(state: DrawingState) -> dict:
    context = state["context"]
    review = state["review"]
    if review["hard_issues"]:
        return {"final_result": TaskResult(status="failed", summary="图稿检查未通过",
                                           error="；".join(review["hard_issues"]))}
    context.check_active()
    result = state["result"]
    source_ids = list(dict.fromkeys(state["source_ids"]))
    name = "mindmap" if state["kind"] == "mindmap" else "flowchart"
    version = int(state["spec"].inputs.get("base_version") or 0) + 1
    diagram_id = context.artifacts.save_text(
        result["xml"], user_id=context.user_id, task_id=context.task_id,
        kind="diagram", filename=f"{name}.drawio", mime_type="application/xml",
        source_ids=source_ids, version=version)
    preview_id = context.artifacts.save_text(
        state["preview"], user_id=context.user_id, task_id=context.task_id,
        kind="preview", filename=f"{name}.svg", mime_type="image/svg+xml",
        source_ids=source_ids, version=version)
    warnings = list(review["layout_issues"])
    if state.get("layout_retry_failed"):
        warnings.append("重排模型请求超时，已保留上一版通过结构校验的可编辑图稿")
    summary = result["summary"]
    if state.get("layout_retry_failed"):
        summary += " 重排请求超时，已保留上一版图稿。"
    return {"final_result": TaskResult(
        status="completed", summary=summary,
        artifact_ids=[diagram_id, preview_id], source_ids=source_ids,
        outputs={"type": state["kind"], "nodes": result["nodes"],
                 "edges": result["edges"], "model": result["model"],
                 "operations": result.get("operations", []),
                 "domain": "drawing", "profile": state["profile"].id,
                 "layout_attempts": state.get("layout_attempts", 0),
                 "layout_retries": max(0, state.get("layout_attempts", 0) - 1),
                 "review": {"approved": not warnings, "warnings": warnings,
                            "fallback_reason": state.get("fallback_reason"),
                            "findings": review["findings"],
                            "canvas": {"width": review["width"], "height": review["height"]}}})}


@lru_cache(maxsize=1)
def drawing_graph():
    """A private domain subgraph invoked from the supervisor's drawing node."""
    graph = StateGraph(DrawingState)
    graph.add_node("domain_supervisor", _domain_supervisor)
    graph.add_node("content_agent", _content_agent)
    graph.add_node("layout_agent", _layout_agent)
    graph.add_node("render_agent", _render_agent)
    graph.add_node("edit_agent", _edit_agent)
    graph.add_node("review_agent", _review_agent)
    graph.add_node("publish", _publish)
    graph.add_edge(START, "domain_supervisor")
    graph.add_conditional_edges("domain_supervisor", lambda state: state["next_agent"])
    graph.add_conditional_edges("content_agent", lambda state: (
        "publish" if state.get("layout_retry_failed") else "layout_agent"))
    graph.add_conditional_edges("layout_agent", lambda state: (
        "publish" if state.get("layout_retry_failed") else "render_agent"))
    graph.add_edge("render_agent", "review_agent")
    graph.add_edge("edit_agent", "review_agent")
    graph.add_conditional_edges("review_agent", _after_review)
    graph.add_edge("publish", END)
    return graph.compile()


def run_domain(spec: TaskSpec, context) -> TaskResult:
    """Translate the task protocol into private state, then return one task result."""
    if spec.constraints.get("output_format") not in {None, "drawio", "xml", "svg"}:
        return TaskResult(status="waiting", error="绘图功能域不支持所需输出格式")
    kind = str(spec.inputs.get("kind") or ("mindmap" if "思维导图" in spec.goal else "flowchart"))
    if kind not in {"flowchart", "mindmap"}:
        raise ValueError("Only flowchart and mindmap are supported")
    prompt = str(spec.inputs.get("query") or spec.goal)
    source_ids = list(spec.inputs.get("source_ids") or [])
    for artifact_id in spec.inputs.get("artifact_ids", []):
        material = context.tool("read_artifact", {"artifact_id": artifact_id,
                                                   "max_chars": 18000})
        prompt += "\n\n参考资料：\n" + material["content"]
        source_ids.extend(material["source_ids"])
    previous_xml = spec.inputs.get("previous_xml")
    if spec.inputs.get("previous_diagram_artifact_id"):
        material = context.tool("read_artifact", {
            "artifact_id": spec.inputs["previous_diagram_artifact_id"],
            "max_chars": 2_000_000,
        })
        previous_xml = material["content"]
        source_ids.extend(material["source_ids"])
    if spec.constraints.get("must_cite_sources") and not source_ids:
        return TaskResult(status="waiting", error="图表缺少可核查的来源资料")
    state: DrawingState = {"context": context, "spec": spec, "prompt": prompt,
                           "kind": kind, "source_ids": source_ids,
                           "previous_xml": previous_xml, "layout_attempts": 0}
    return drawing_graph().invoke(state, config={"recursion_limit": 24})["final_result"]
