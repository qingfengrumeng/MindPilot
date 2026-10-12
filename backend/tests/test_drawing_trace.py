"""The monitor reveals only runtime events that have happened."""

from datetime import datetime, timedelta
from types import SimpleNamespace

from app.plugins.diagram_agent.trace import drawing_trace


def test_drawing_trace_reveals_events_without_predicted_stages():
    root_id, child_id = "root-1", "child-1"
    origin = datetime(2026, 1, 1, 12, 0, 0)
    root_events, child_events = [], []

    def record(events, kind, seconds, detail=None):
        events.append({"id": f"event-{len(root_events) + len(child_events)}",
                       "kind": kind, "detail": detail or {},
                       "createdAt": (origin + timedelta(seconds=seconds)).isoformat()})

    class Manager:
        def get(self, task_id, *, user_id):
            if not root_events:
                raise KeyError(task_id)
            return SimpleNamespace(status="running")

        def children(self, task_id, *, user_id):
            return [SimpleNamespace(task_id=child_id)] if child_events else []

        def events(self, task_id, *, user_id):
            return root_events if task_id == root_id else child_events

    manager = Manager()

    def trace():
        return drawing_trace(manager, root_id, "user-1", "绘制流程图")

    assert trace()["stages"] == []
    record(root_events, "created", 0)
    assert [stage["title"] for stage in trace()["stages"]] == ["分析绘图需求"]
    assert trace()["stages"][0]["status"] == "running"

    record(root_events, "turn_start", 1, {"agent": "supervisor"})
    stages = trace()["stages"]
    assert [stage["title"] for stage in stages] == ["分析绘图需求", "主 Agent · 任务调度"]
    assert stages[0]["durationMs"] == 1000
    assert stages[1]["status"] == "running"

    record(root_events, "plan", 2, {"steps": [{"intent": "flowchart"}]})
    assert trace()["stages"][1]["status"] == "running"
    record(root_events, "dispatch_handoff", 3,
           {"child_task_id": child_id, "agent": "diagram_agent"})
    assert trace()["stages"][1]["durationMs"] == 2000

    record(child_events, "turn_start", 4, {"agent": "diagram_agent"})
    stages = trace()["stages"]
    assert [stage["title"] for stage in stages] == [
        "分析绘图需求", "主 Agent · 任务调度", "进入绘图功能域"]
    assert stages[-1]["status"] == "ok"
    assert "durationMs" not in stages[-1]
    assert not any(stage["kind"] == "skill" for stage in stages)

    record(child_events, "drawing_stage", 5,
           {"stage": "content_planning", "status": "running", "attempt": 1})
    assert trace()["stages"][-1]["title"] == "内容规划 Agent"
    assert trace()["stages"][-1]["status"] == "running"
    assert not any(stage["kind"] == "tool" for stage in trace()["stages"])

    record(child_events, "model_request", 6,
           {"request_id": "request-1", "purpose": "drawing_content", "model": "test"})
    assert trace()["stages"][-1]["title"] == "模型调用 · 内容规划"
    record(child_events, "model_response", 7, {"request_id": "request-1"})
    assert trace()["stages"][-1]["status"] == "ok"

    record(child_events, "drawing_stage", 8,
           {"stage": "content_planning", "status": "completed", "attempt": 1,
            "nodes": 2, "edges": 1})
    assert trace()["stages"][3]["durationMs"] == 3000
    assert not any("重试" in stage["title"] for stage in trace()["stages"])

    record(child_events, "drawing_relayout", 9,
           {"retry": 1, "findings": [{"problem": "拥挤", "suggestion": "加大间距"}]})
    assert trace()["stages"][-1]["title"] == "重试 · 返回内容规划 Agent"
    assert trace()["stages"][-1]["detail"]["findings"][0]["suggestion"] == "加大间距"


def test_domain_supervisor_stage_appears_only_when_dispatched():
    origin = datetime(2026, 1, 1, 12, 0, 0)
    root_events = [{"id": "r1", "kind": "created", "detail": {},
                    "createdAt": origin.isoformat()}]
    child_events = []

    class Manager:
        def get(self, task_id, *, user_id):
            return SimpleNamespace(status="running")

        def children(self, task_id, *, user_id):
            return [SimpleNamespace(task_id="child")]

        def events(self, task_id, *, user_id):
            return root_events if task_id == "root" else child_events

    def titles():
        return [stage["title"] for stage in drawing_trace(
            Manager(), "root", "user", "绘制流程图")["stages"]]

    assert "绘图域总控 Agent" not in titles()
    child_events.append({"id": "c1", "kind": "drawing_stage",
                         "detail": {"stage": "domain_supervisor", "status": "running",
                                    "attempt": 1},
                         "createdAt": (origin + timedelta(seconds=1)).isoformat()})
    assert titles()[-1] == "绘图域总控 Agent"
    child_events.append({"id": "c2", "kind": "drawing_stage",
                         "detail": {"stage": "domain_supervisor", "status": "completed",
                                    "attempt": 1, "profile": "flowchart",
                                    "next_agent": "content_agent"},
                         "createdAt": (origin + timedelta(seconds=2)).isoformat()})
    stage = drawing_trace(Manager(), "root", "user", "绘制流程图")["stages"][-1]
    assert stage["durationMs"] == 1000
    assert stage["detail"]["profile"] == "flowchart"
