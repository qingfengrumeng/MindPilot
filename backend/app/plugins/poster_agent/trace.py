"""Build a live timeline only from stages that actually began."""

from __future__ import annotations

from datetime import datetime


TITLES = {"asset_analysis": "素材理解 Agent · 看图与定位",
          "supervisor": "海报主管 Agent · 理解与调度", "research": "资料搜索工具",
          "design": "视觉设计 Agent", "render": "HTML 与截图渲染工具",
          "review": "图稿质检 Agent", "publish": "保存与导出",
          "image_generation": "生成视觉元素工具"}


def _ms(start: str, end: str) -> int:
    return max(1, round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() * 1000))


def poster_trace(manager, task_id: str, user_id: str, query: str) -> dict:
    try:
        task = manager.get(task_id, user_id=user_id)
    except KeyError:
        return {"runId": task_id, "domain": "poster", "status": "running",
                "query": query[:300], "durationMs": 0, "stages": []}
    children = manager.children(task_id, user_id=user_id)
    events = [(task_id, row) for row in manager.events(task_id, user_id=user_id)]
    for child in children:
        events.extend((child.task_id, row) for row in manager.events(child.task_id, user_id=user_id))
    events.sort(key=lambda item: (item[1]["createdAt"], item[1]["id"]))
    stages, active = [], {}

    def begin(event, kind, title, summary="执行中", status="running"):
        stage = {"id": event["id"], "kind": kind, "title": title, "status": status,
                 "summary": summary, "detail": {}, "startedAt": event["createdAt"]}
        stages.append(stage)
        return stage

    def finish(stage, event, status="ok", summary="已完成"):
        if stage and stage["status"] == "running":
            stage.update(status=status, summary=summary, durationMs=_ms(stage["startedAt"], event["createdAt"]))

    for owner, event in events:
        kind, detail = event["kind"], event["detail"]
        if owner == task_id and kind == "created":
            active["analysis"] = begin(event, "input", "分析海报需求", "识别目标与所需素材")
        elif owner == task_id and kind == "turn_start":
            finish(active.get("analysis"), event, summary="需求已进入任务队列")
            active["main"] = begin(event, "agent", "主 Agent · 任务调度", "正在选择海报功能域")
        elif owner == task_id and kind == "dispatch_handoff":
            finish(active.get("main"), event, summary="已交给海报功能域")
        elif owner != task_id and kind == "turn_start":
            begin(event, "domain", "进入海报功能域", "域内工作流已启动", "ok")
        elif kind == "poster_stage":
            name, status = detail.get("stage"), detail.get("status")
            key = (name, detail.get("attempt", 0))
            if status == "running":
                active[key] = begin(event, "agent" if name in {"asset_analysis", "supervisor", "design", "review"} else "tool",
                                    TITLES.get(name, name))
            else:
                stage = active.get(key)
                if status == "completed" and stage is None:
                    stage = begin(event, "tool", TITLES.get(name, name))
                if stage:
                    stage["detail"] = {key: value for key, value in detail.items()
                                       if key not in {"status", "stage"}}
                finish(stage, event, "empty" if status == "needs_revision" else "ok",
                       "发现问题，返回设计 Agent" if status == "needs_revision" else "已完成")
        elif kind == "model_request":
            active[("model", detail.get("request_id"))] = begin(
                event, "model", "模型调用 · " + str(detail.get("purpose") or "生成"), "等待模型响应")
        elif kind in {"model_response", "model_attempt"}:
            finish(active.get(("model", detail.get("request_id"))), event,
                   "error" if kind == "model_attempt" else "ok",
                   detail.get("error", "模型已响应") if kind == "model_attempt" else "模型已响应")
        elif kind == "tool_call":
            active[("tool", detail.get("step_id"))] = begin(
                event, "tool", "工具调用 · " + str(detail.get("tool") or "工具"))
        elif kind == "tool_result":
            finish(active.get(("tool", detail.get("step_id"))), event,
                   "error" if detail.get("status") == "failed" else "ok",
                   detail.get("error", "工具已完成") if detail.get("status") == "failed" else "工具已完成")
        elif kind == "poster_revision":
            stage = begin(event, "agent", "质检反馈 · 返回视觉设计", "携带问题与建议重新设计", "ok")
            stage["detail"] = {"issues": detail.get("issues", [])}
    if task.status in {"failed", "cancelled"}:
        for stage in stages:
            if stage["status"] == "running":
                stage.update(status="error", summary=task.error or "任务中断")
    return {"runId": task_id, "domain": "poster", "status": task.status,
            "query": query[:300], "durationMs": sum(stage.get("durationMs", 0) for stage in stages),
            "stages": stages}
