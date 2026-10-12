"""Turn persisted drawing runtime events into a live, user-facing timeline."""

from __future__ import annotations

from datetime import datetime


STAGES = {
    "domain_supervisor": ("绘图域总控 Agent", "agent"),
    "content_planning": ("内容规划 Agent", "agent"),
    "layout_design": ("排版 Agent", "agent"),
    "diagram_generation": ("绘图工具 Agent", "agent"),
    "diagram_review": ("图稿检查 Agent", "agent"),
    "precise_edit": ("图稿编辑 Agent", "agent"),
}
MODELS = {
    "drawing_content": "内容规划",
    "drawing_layout": "排版设计",
    "drawing_review": "图稿检查",
}


def _tool_arguments(arguments: dict) -> dict:
    """Keep live timeline updates small while retaining the useful call parameters."""
    result = {}
    for key, value in arguments.items():
        if key == "plan" and isinstance(value, dict):
            result[key] = {"nodes": len(value.get("nodes", [])),
                           "edges": len(value.get("edges", []))}
        elif isinstance(value, (dict, list)):
            result[key] = {"items": len(value)}
        elif isinstance(value, str) and len(value) > 240:
            result[key] = {"characters": len(value)}
        else:
            result[key] = value
    return result


def _elapsed(start: str, end: str) -> int:
    return max(1, round((datetime.fromisoformat(end)
                         - datetime.fromisoformat(start)).total_seconds() * 1000))


def drawing_trace(manager, task_id: str, user_id: str, query: str) -> dict:
    """A stable stage ID is updated as its corresponding runtime event settles."""
    try:
        task = manager.get(task_id, user_id=user_id)
    except KeyError:
        return {"runId": task_id, "domain": "drawing", "status": "running",
                "query": query[:300], "durationMs": 0, "stages": []}
    children = manager.children(task_id, user_id=user_id)
    events = [(task_id, event) for event in manager.events(task_id, user_id=user_id)]
    for child in children:
        events.extend((child.task_id, event)
                      for event in manager.events(child.task_id, user_id=user_id))
    events.sort(key=lambda item: (item[1]["createdAt"], item[1]["id"]))
    stages = []
    active = {}

    def begin(event: dict, kind: str, title: str, summary: str, detail=None,
              status: str = "running") -> dict:
        stage = {"id": event["id"], "kind": kind, "title": title,
                 "status": status, "summary": summary, "detail": detail or {},
                 "startedAt": event["createdAt"]}
        stages.append(stage)
        return stage

    def settle(stage: dict | None, event: dict, status: str, summary: str = "") -> None:
        if stage is None or stage["status"] != "running":
            return
        stage["status"] = status
        if summary:
            stage["summary"] = summary
        stage["durationMs"] = _elapsed(stage["startedAt"], event["createdAt"])

    for owner, event in events:
        kind, detail = event["kind"], event["detail"]
        if kind == "created" and owner == task_id:
            active["analysis"] = begin(event, "input", "分析绘图需求",
                                       "正在识别绘图目标", {"query": query[:300]})
        elif kind == "turn_start" and owner == task_id:
            settle(active.get("analysis"), event, "ok", "已识别绘图请求")
            active["supervisor"] = begin(event, "agent", "主 Agent · 任务调度",
                                         "正在选择并调度绘图能力")
        elif kind == "plan" and owner == task_id:
            stage = active.get("supervisor")
            if stage is not None:
                stage["summary"] = "已确定执行计划，正在创建子任务"
                stage["detail"] = {"steps": detail.get("steps", [])}
        elif kind == "dispatch_handoff" and owner == task_id:
            stage = active.get("supervisor")
            if stage is not None:
                stage["detail"].update({"childTaskId": detail.get("child_task_id"),
                                        "agent": detail.get("agent")})
            settle(stage, event, "ok", "已将任务交给绘图功能域")
        elif kind == "turn_start" and owner != task_id:
            begin(event, "domain", "进入绘图功能域", "绘图域已接收任务",
                  {"agent": detail.get("agent"), "taskId": owner}, status="ok")
        elif kind == "skill_loaded":
            begin(event, "skill", f"加载 Skill · {detail.get('skill', '未知')}",
                  "已读取 Skill 指令",
                  {"skill": detail.get("skill"), "agent": detail.get("agent")}, status="ok")
        elif kind == "drawing_stage":
            stage_name = detail.get("stage")
            title, stage_kind = STAGES.get(stage_name, ("绘图步骤", "agent"))
            key = (stage_name, detail.get("attempt", 0))
            if detail.get("status") == "running":
                active[key] = begin(event, stage_kind, title,
                                    "执行中", {"attempt": detail.get("attempt")})
            elif detail.get("status") in {"completed", "needs_revision"}:
                stage = active.get(key)
                if stage is None:
                    stage = begin(event, stage_kind, title, "执行中")
                warning = detail["status"] == "needs_revision"
                stage["detail"] = {field: detail[field] for field in
                                   ("attempt", "nodes", "edges", "issues", "findings", "canvas",
                                    "profile", "next_agent", "has_review_feedback")
                                   if field in detail}
                settle(stage, event, "empty" if warning else "ok",
                       "发现问题，准备重试" if warning else "已完成")
        elif kind == "model_request":
            purpose = detail.get("purpose", "generation")
            active[("model", detail.get("request_id"))] = begin(
                event, "model", f"模型调用 · {MODELS.get(purpose, purpose)}",
                "等待模型响应", {"model": detail.get("model"), "purpose": purpose,
                                  "requestArtifactId": detail.get("request_artifact_id")})
        elif kind in {"model_response", "model_attempt"}:
            stage = active.get(("model", detail.get("request_id")))
            failed = kind == "model_attempt"
            if stage is not None:
                stage["detail"].update({field: detail[field] for field in
                                        ("latency_ms", "error", "cause_type",
                                         "response_artifact_id") if field in detail})
            settle(stage, event, "error" if failed else "ok",
                   detail.get("error", "模型已响应") if failed else "模型已响应")
        elif kind == "tool_call":
            tool = detail.get("tool", "tool")
            active[("tool", detail.get("step_id"))] = begin(
                event, "tool", f"工具调用 · {tool}", "正在执行",
                {"tool": tool, "arguments": _tool_arguments(detail.get("arguments", {}))})
        elif kind == "tool_result":
            stage = active.get(("tool", detail.get("step_id")))
            failed = detail.get("status") == "failed"
            if stage is not None:
                stage["detail"].update({field: detail[field] for field in ("result", "error")
                                        if field in detail})
            settle(stage, event, "error" if failed else "ok",
                   detail.get("error", "工具执行失败") if failed else "工具已完成")
        elif kind == "drawing_relayout":
            begin(event, "agent", "重试 · 返回内容规划 Agent",
                  f"第 {detail.get('retry', 1)} 次重试，携带问题和修改建议",
                  {"findings": detail.get("findings", [])}, status="ok")
        elif kind in {"drawing_layout_fallback", "drawing_content_fallback"}:
            stage_name = "layout_design" if kind == "drawing_layout_fallback" else "content_planning"
            settle(active.get((stage_name, detail.get("attempt", 0))), event,
                   "empty", "模型请求失败，已采用备用方案")
            reuse = kind == "drawing_content_fallback" or detail.get("using_previous_draft")
            begin(event, "agent", "保留上一版图稿" if reuse else "使用备用排版",
                  "模型请求失败，保留上一版图稿" if reuse else "排版模型请求失败，改用确定性布局",
                  {"reason": detail.get("reason")}, status="empty")
        elif kind == "turn_end" and owner != task_id:
            for stage in stages:
                if stage["status"] == "running":
                    settle(stage, event, "error" if detail.get("status") == "failed" else "empty",
                           "执行中断" if detail.get("status") == "failed" else "未完成")
        elif kind == "turn_end" and owner == task_id:
            settle(active.get("supervisor"), event,
                   "error" if detail.get("status") == "failed" else "ok",
                   "主 Agent 执行失败" if detail.get("status") == "failed" else "调度已结束")
        elif kind == "status" and owner == task_id and detail.get("status") in {
                "completed", "failed", "cancelled"}:
            failed = detail["status"] != "completed"
            for stage in stages:
                if stage["status"] == "running":
                    settle(stage, event, "error" if failed else "empty",
                           "任务中断" if failed else "未完成")
            begin(event, "output", "绘图任务结束",
                  detail.get("error", "绘图任务失败") if failed else "图稿已生成",
                  status="error" if failed else "ok")

    duration_ms = _elapsed(events[0][1]["createdAt"], events[-1][1]["createdAt"]) if len(events) > 1 else 0
    status = "error" if task.status in {"failed", "cancelled"} else (
        "ok" if task.status == "completed" else "running")
    return {"runId": task_id, "domain": "drawing", "status": status,
            "query": query[:300], "durationMs": duration_ms, "stages": stages}
