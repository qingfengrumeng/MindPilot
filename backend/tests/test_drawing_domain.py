"""The drawing subgraph reviews the artifact and retries from content planning."""

from dataclasses import asdict
import json
import xml.etree.ElementTree as ET

import pytest

from app.plugins.diagram_agent.domain import run_domain
from app.runtime.protocol import TaskSpec
from app.services.text_generation import TextGenerationError
from app.skills.drawing_engine import build_diagram
from app.skills.drawing_profiles import load_drawing_profile
from app.agents.drawing_content import content_messages
from app.plugins.diagram_agent import domain as drawing_domain


@pytest.mark.parametrize("recover_on", [4, None])
def test_drawing_domain_retries_three_times_with_findings_and_suggestions(recover_on):
    plan = {
        "nodes": [{"id": f"n{index}", "label": f"步骤 {index}", "kind": "process"}
                  for index in range(6)],
        "edges": [{"source": f"n{index}", "target": f"n{index + 1}"}
                  for index in range(5)],
    }

    class Artifacts:
        def __init__(self):
            self.saved = []

        def save_text(self, text, **metadata):
            self.saved.append((text, metadata))
            return f"artifact-{len(self.saved)}"

    class Context:
        def __init__(self):
            self.user_id = "user-1"
            self.task_id = "task-1"
            self.artifacts = Artifacts()
            self.events = []
            self.layout_prompts = []
            self.content_prompts = []
            self.render_count = 0

        def check_active(self):
            pass

        def event(self, kind, detail):
            self.events.append((kind, detail))

        def model(self, messages, *, purpose, complete_fn):
            if purpose == "drawing_content":
                self.content_prompts.append(messages)
                return json.dumps(plan, ensure_ascii=False), {"model": "fake"}
            if purpose == "drawing_review":
                return '{"approved":true,"feedback":""}', {"model": "fake"}
            self.layout_prompts.append(messages)
            return json.dumps({"layout_mode": "flow",
                               "node_order": [node["id"] for node in plan["nodes"]]}), {"model": "fake"}

        def tool(self, name, arguments):
            assert name == "diagram_render"
            self.render_count += 1
            diagram = asdict(build_diagram(arguments["plan"], arguments["kind"]))
            if recover_on is None or self.render_count < recover_on:
                model = ET.fromstring(diagram["xml"])
                geometry = model.find("./root/mxCell[@id='n5']/mxGeometry")
                geometry.set("y", "5000")
                diagram["xml"] = ET.tostring(model, encoding="unicode")
            return {**diagram, "model": "fake"}

    context = Context()
    result = run_domain(TaskSpec(agent="diagram_agent", goal="绘制六步流程",
                                 inputs={"kind": "flowchart"}), context)

    assert result.status == "completed"
    assert result.outputs["layout_attempts"] == 4
    assert result.outputs["layout_retries"] == 3
    assert result.outputs["profile"] == "flowchart"
    assert result.outputs["review"]["approved"] is (recover_on is not None)
    assert result.artifact_ids == ["artifact-1", "artifact-2"]
    assert context.render_count == 4
    assert "宽高比例过大" in context.layout_prompts[1][-1]["content"]
    assert '"problem"' in context.layout_prompts[1][-1]["content"]
    assert '"suggestion"' in context.layout_prompts[1][-1]["content"]
    assert len([event for event in context.events if event[0] == "drawing_relayout"]) == 3
    supervisor_calls = [detail for kind, detail in context.events
                        if kind == "drawing_stage" and detail.get("stage") == "domain_supervisor"
                        and detail.get("status") == "completed"]
    assert len(supervisor_calls) == 4
    assert [detail["has_review_feedback"] for detail in supervisor_calls] == [False, True, True, True]
    assert '"problem"' in context.content_prompts[1][-1]["content"]
    assert '"suggestion"' in context.content_prompts[1][-1]["content"]
    assert [detail["agent"] for kind, detail in context.events
            if kind == "drawing_agent_handoff"] == [
                agent for _ in range(4)
                for agent in ("content_agent", "layout_agent", "render_agent", "review_agent")
            ]
    if recover_on is None:
        assert result.outputs["review"]["findings"][0]["suggestion"]
        assert result.outputs["review"]["warnings"]
        assert any(kind == "drawing_review_exhausted" for kind, _ in context.events)


def test_profiles_keep_one_workflow_with_distinct_drawing_rules():
    flow = load_drawing_profile("flowchart")
    mindmap = load_drawing_profile("mindmap")
    assert flow.connector_end_arrow == "block"
    assert mindmap.connector_end_arrow == "none"
    assert flow.max_retries == mindmap.max_retries == 3
    assert "执行顺序" in content_messages("审批申请", "flowchart", profile=flow)[0]["content"]
    assert "中心主题" in content_messages("知识结构", "mindmap", profile=mindmap)[0]["content"]


def test_drawing_domain_keeps_valid_draft_when_relayout_model_times_out():
    plan = {"nodes": [{"id": "topic", "label": "主题"},
                      {"id": "method", "label": "方法"},
                      {"id": "result", "label": "结果"}],
            "edges": [{"source": "topic", "target": "method"},
                      {"source": "topic", "target": "result"}]}

    class Context:
        user_id = "user-1"
        task_id = "task-1"

        def __init__(self):
            self.events = []
            self.layout_calls = 0
            self.render_calls = 0
            self.artifacts = self

        def save_text(self, text, **metadata):
            return f"artifact-{metadata['kind']}"

        def check_active(self):
            pass

        def event(self, kind, detail):
            self.events.append((kind, detail))

        def model(self, messages, *, purpose, complete_fn):
            if purpose == "drawing_content":
                return json.dumps(plan, ensure_ascii=False), {"model": "fake"}
            if purpose == "drawing_review":
                return ('{"approved":false,"problem":"分支略显拥挤",'
                        '"suggestion":"调整左右分支顺序"}', {"model": "fake"})
            self.layout_calls += 1
            if self.layout_calls == 2:
                raise TextGenerationError("DeepSeek 响应超时，请稍后重试")
            return '{"layout_mode":"mindmap"}', {"model": "fake"}

        def tool(self, name, arguments):
            self.render_calls += 1
            return {**asdict(build_diagram(arguments["plan"], "mindmap")), "model": "fake"}

    context = Context()
    result = run_domain(TaskSpec(agent="diagram_agent", goal="绘制思维导图",
                                 inputs={"kind": "mindmap"}), context)
    assert result.status == "completed"
    assert context.render_calls == 1
    assert result.outputs["layout_attempts"] == 2
    assert result.outputs["review"]["fallback_reason"] == "DeepSeek 响应超时，请稍后重试"
    assert "重排请求超时" in result.summary
    assert any(kind == "drawing_layout_fallback" for kind, _ in context.events)


def test_drawing_domain_replans_after_structural_review_failure(monkeypatch):
    plan = {"nodes": [{"id": "a", "label": "开始"}, {"id": "b", "label": "完成"}],
            "edges": [{"source": "a", "target": "b"}]}
    inspected = drawing_domain.inspect_diagram
    calls = 0

    def inspect_once(xml, svg, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"approved": False, "hard_issues": ["图稿缺少已规划节点"],
                    "layout_issues": [], "findings": [], "width": 640, "height": 420}
        return inspected(xml, svg, **kwargs)

    monkeypatch.setattr(drawing_domain, "inspect_diagram", inspect_once)

    class Context:
        user_id = "user-1"
        task_id = "task-1"

        def __init__(self):
            self.artifacts = self
            self.events = []
            self.content_prompts = []

        def check_active(self):
            pass

        def event(self, kind, detail):
            self.events.append((kind, detail))

        def save_text(self, text, **metadata):
            return metadata["kind"]

        def model(self, messages, *, purpose, complete_fn):
            if purpose == "drawing_content":
                self.content_prompts.append(messages)
                return json.dumps(plan, ensure_ascii=False), {}
            if purpose == "drawing_layout":
                return '{"layout_mode":"flow"}', {}
            return '{"approved":true}', {}

        def tool(self, name, arguments):
            return {**asdict(build_diagram(arguments["plan"], "flowchart")),
                    "model": "fake"}

    context = Context()
    result = run_domain(TaskSpec(agent="diagram_agent", goal="绘制流程",
                                 inputs={"kind": "flowchart"}), context)
    assert result.status == "completed"
    assert calls == 2
    assert "图稿缺少已规划节点" in context.content_prompts[1][-1]["content"]
    assert "修改建议" in context.content_prompts[1][-1]["content"]
