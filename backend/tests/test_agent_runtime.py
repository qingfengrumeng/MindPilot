from app.core.model_preferences import write_preferences
"""The runtime executes plugins from manifests and persists parent/child handoffs."""

from dataclasses import asdict
import json
from time import sleep

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.db.models import User
from app.main import create_app
from app.runtime.agent_registry import AgentRegistry
from app.runtime.protocol import TaskSpec
from app.runtime.tool_registry import ToolRegistry
from app.skills.drawing_engine import build_diagram


def _client(tmp_path, monkeypatch):
    env = tmp_path / "models.json"
    write_preferences(env, {'providers': {'deepseek': {'name': 'deepseek', 'runtimeProvider': 'deepseek', 'apiKey': 'test-key', 'configs': {'text': {'baseUrl': 'https://api.deepseek.com', 'model': 'deepseek-flash'}}}}, 'active': {'text': 'deepseek'}})
    for name in ("PROVIDER", "BASE_URL", "MODEL", "API_KEY"):
        monkeypatch.delenv(f"MINDPILOT_TEXT_{name}", raising=False)
    monkeypatch.setattr("app.skills.ai_drawing.complete_text",
                        lambda config, messages: (json.dumps({
                            "nodes": [{"id": "begin", "label": "Start", "kind": "start"},
                                      {"id": "finish", "label": "Finish", "kind": "end"}],
                            "edges": [{"source": "begin", "target": "finish"}]
                        }), {"model": "fake-model"}))
    settings = Settings(database_url=f"sqlite:///{(tmp_path / 'runtime.db').as_posix()}",
                        jwt_secret="test-secret-longer-than-thirty-two-bytes-for-jwt",
                        allowed_origins=("http://localhost:5173",), model_config_path=env,
                        data_dir=tmp_path)
    app = create_app(settings)
    return app, TestClient(app)


def _login(client, username):
    client.post("/api/v1/auth/register", json={"username": username, "password": "strong-password-123"})
    token = client.post("/api/v1/auth/login", json={"username": username,
                                                    "password": "strong-password-123"}).json()["accessToken"]
    return {"Authorization": f"Bearer {token}"}


def test_supervisor_dispatches_manifest_plugin_and_persists_artifacts(tmp_path, monkeypatch):
    app, test_client = _client(tmp_path, monkeypatch)
    schema, _ = app.state.tool_registry._tools["diagram_render"]

    def fake_render(arguments, context):
        plan = {"nodes": [{"id": "begin", "label": "Start", "kind": "start"},
                          {"id": "finish", "label": "Finish", "kind": "end"}],
                "edges": [{"source": "begin", "target": "finish"}]}
        return {**asdict(build_diagram(plan, arguments.kind)), "model": "fake-model"}

    app.state.tool_registry._tools["diagram_render"] = (schema, fake_render)
    with test_client as client:
        headers = _login(client, "alice")
        conversation = client.post("/api/v1/conversations", headers=headers,
                                   json={"title": "Agent runtime"}).json()
        catalog = client.get("/api/v1/agent-modules", headers=headers).json()
        assert {row["id"] for row in catalog["agents"]} == {"knowledge_agent", "diagram_agent", "research_agent", "poster_agent"}
        assert "markdown_formatting" in {row["id"] for row in catalog["skills"]}
        result = client.post("/api/v1/agent-tasks", headers=headers, json={
            "agent": "supervisor", "goal": "画一个流程图", "inputs": {"steps": ["flowchart"]},
            "conversation_id": conversation["id"]}).json()
        assert result["status"] == "completed", result
        assert len(result["result"]["artifact_ids"]) == 2
        details = client.get(f"/api/v1/agent-tasks/{result['task_id']}", headers=headers).json()
        assert details["children"][0]["parent_task_id"] == result["task_id"]
        assert details["children"][0]["agent"] == "diagram_agent"
        assert any(row["kind"] == "child_result" for row in details["events"])
        trace = client.get(f"/api/v1/agent-tasks/{result['task_id']}/trace", headers=headers).json()
        assert {row["agent"] for row in trace["events"]} == {"supervisor", "diagram_agent"}
        assert any(row["kind"] == "tool_call" and row["agent"] == "diagram_agent"
                   for row in trace["events"])
        diagram_id = result["result"]["artifact_ids"][0]
        artifact = client.get(f"/api/v1/agent-artifacts/{diagram_id}", headers=headers)
        assert artifact.status_code == 200
        assert "mxGraphModel" in artifact.text
        bob = _login(client, "bob")
        assert client.get(f"/api/v1/agent-tasks/{result['task_id']}", headers=bob).status_code == 404
        assert client.get(f"/api/v1/agent-tasks/{result['task_id']}/trace", headers=bob).status_code == 404
        assert client.get(f"/api/v1/agent-artifacts/{diagram_id}", headers=bob).status_code == 404


def test_missing_plugin_waits_and_markdown_skill_stays_in_supervisor(tmp_path, monkeypatch):
    app, test_client = _client(tmp_path, monkeypatch)
    monkeypatch.setattr("app.agents.supervisor.complete_text",
                        lambda config, messages: ("# 标题\n\n整理后的正文。", {"model": "fake-model"}))
    with test_client as client:
        headers = _login(client, "alice")
        missing = client.post("/api/v1/agent-tasks", headers=headers,
                              json={"goal": "制作 PPT", "inputs": {"steps": ["presentation"]}}).json()
        assert missing["status"] == "waiting"
        assert "没有安装" in missing["error"]
        markdown = client.post("/api/v1/agent-tasks", headers=headers,
                               json={"goal": "整理成 Markdown", "inputs": {"steps": ["markdown_formatting"],
                                                                       "content": "一段原始内容"}}).json()
        assert markdown["status"] == "completed", markdown
        assert markdown["result"]["outputs"]["child_task_ids"] == []
        artifact = client.get(f"/api/v1/agent-artifacts/{markdown['result']['artifact_ids'][0]}",
                              headers=headers)
        assert "整理后的正文" in artifact.text


def test_supervisor_uses_registered_capability_summaries_for_unmatched_goal(tmp_path, monkeypatch):
    app, test_client = _client(tmp_path, monkeypatch)
    seen = []
    schema, _ = app.state.tool_registry._tools["diagram_render"]
    app.state.tool_registry._tools["diagram_render"] = (
        schema, lambda arguments, context: {
            **asdict(build_diagram(arguments.plan, arguments.kind)), "model": "fake-model"})

    def plan(config, messages):
        seen.append(messages)
        return ('{"steps":[{"intent":"flowchart"}]}', {"model": "fake-model"})

    monkeypatch.setattr("app.agents.supervisor.complete_text", plan)
    with test_client as client:
        headers = _login(client, "alice")
        result = client.post("/api/v1/agent-tasks", headers=headers, json={
            "goal": "描绘实体之间的关系"}).json()
        assert result["status"] == "completed", result
        assert seen and "research_agent" in seen[0][1]["content"]
        trace = client.get(f"/api/v1/agent-tasks/{result['task_id']}/trace", headers=headers).json()
        assert any(row["kind"] == "model_request" and
                   row["detail"]["purpose"] == "supervisor_planning" for row in trace["events"])
        assert any(row["kind"] == "plan" and
                   row["detail"]["steps"][0]["intent"] == "flowchart"
                   for row in trace["events"])


def test_retry_reuses_completed_child_before_missing_capability(tmp_path, monkeypatch):
    app, test_client = _client(tmp_path, monkeypatch)
    schema, _ = app.state.tool_registry._tools["diagram_render"]
    calls = []

    def fake_render(arguments, context):
        calls.append(arguments.prompt)
        result = build_diagram(arguments.plan, arguments.kind)
        return {**asdict(result), "model": "fake-model"}

    app.state.tool_registry._tools["diagram_render"] = (schema, fake_render)
    with test_client as client:
        headers = _login(client, "alice")
        task = client.post("/api/v1/agent-tasks", headers=headers,
                           json={"goal": "画流程图并制作 PPT", "inputs": {"steps": ["flowchart", "presentation"]}}).json()
        assert task["status"] == "waiting"
        assert len(calls) == 1
        retried = client.post(f"/api/v1/agent-tasks/{task['task_id']}/retry", headers=headers).json()
        assert retried["status"] == "waiting"
        assert len(calls) == 1
        details = client.get(f"/api/v1/agent-tasks/{task['task_id']}", headers=headers).json()
        assert len(details["children"]) == 1
        assert any(event["kind"] == "reuse_child" for event in details["events"])


def test_research_plugin_returns_cited_report_artifact(tmp_path, monkeypatch):
    app, test_client = _client(tmp_path, monkeypatch)
    schema, _ = app.state.tool_registry._tools["web_search"]
    app.state.tool_registry._tools["web_search"] = (
        schema, lambda arguments, context: {"context": "[网页1] A study found an improvement.",
                                             "sources": [{"title": "Study", "url": "https://example.org/study"}],
                                             "source_ids": ["https://example.org/study"],
                                             "status": "ok", "error": None})
    monkeypatch.setattr("app.plugins.research_agent.agent.complete_text",
                        lambda config, messages: ("# Research\n\nA study found an improvement [Study](https://example.org/study).",
                                                  {"model": "fake-model"}))
    with test_client as client:
        headers = _login(client, "alice")
        result = client.post("/api/v1/agent-tasks", headers=headers,
                             json={"agent": "research_agent", "goal": "Research this topic",
                                   "inputs": {"query": "RAG", "source_scope": "web"}}).json()
        assert result["status"] == "completed", result
        assert result["result"]["source_ids"] == ["https://example.org/study"]
        report = client.get(f"/api/v1/agent-artifacts/{result['result']['artifact_ids'][0]}",
                            headers=headers)
        assert "https://example.org/study" in report.text
        detail = client.get(f"/api/v1/agent-tasks/{result['task_id']}", headers=headers).json()
        events = detail["events"]
        requests = [item["detail"] for item in events if item["kind"] == "model_request"]
        responses = [item["detail"] for item in events if item["kind"] == "model_response"]
        assert len(requests) == len(responses) == 1
        assert requests[0]["request_id"] == responses[0]["request_id"]
        assert requests[0]["step_id"] == responses[0]["step_id"]
        request_file = client.get(
            f"/api/v1/agent-artifacts/{requests[0]['request_artifact_id']}", headers=headers).json()
        assert request_file["messages"][1]["content"].startswith("研究问题：RAG")
        assert client.get(f"/api/v1/agent-artifacts/{responses[0]['response_artifact_id']}",
                          headers=headers).text.startswith("# Research")
        assert any(item["kind"] == "artifact_saved" and
                   item["detail"]["artifact_id"] == result["result"]["artifact_ids"][0]
                   for item in events)
        assert any(item["kind"] == "step_start" for item in events)
        assert any(item["kind"] == "step_end" for item in events)
        assert any(item["kind"] == "tool_result" and
                   item["detail"]["result"]["source_ids"] == ["https://example.org/study"]
                   for item in events)


def test_failed_model_attempt_is_recorded_without_false_completion(tmp_path, monkeypatch):
    app, test_client = _client(tmp_path, monkeypatch)
    schema, _ = app.state.tool_registry._tools["web_search"]
    app.state.tool_registry._tools["web_search"] = (
        schema, lambda arguments, context: {"context": "Evidence", "sources": [],
                                             "source_ids": [], "status": "ok", "error": None})

    def fail_model(config, messages):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr("app.plugins.research_agent.agent.complete_text", fail_model)
    with test_client as client:
        headers = _login(client, "alice")
        result = client.post("/api/v1/agent-tasks", headers=headers, json={
            "agent": "research_agent", "goal": "Research", "inputs": {"source_scope": "web"}}).json()
        assert result["status"] == "failed"
        detail = client.get(f"/api/v1/agent-tasks/{result['task_id']}", headers=headers).json()
        assert any(item["kind"] == "model_attempt" and
                   item["detail"]["status"] == "failed" for item in detail["events"])
        assert not any(item["kind"] == "model_response" for item in detail["events"])
        assert any(item["kind"] == "turn_end" and item["detail"]["status"] == "failed"
                   for item in detail["events"])


def test_registry_rejects_plugins_with_missing_tools():
    registry = AgentRegistry(ToolRegistry())
    try:
        registry.discover()
    except ValueError as exc:
        assert "requires missing tools" in str(exc)
    else:
        raise AssertionError("A plugin with unavailable tools was registered")


def test_interrupted_task_becomes_retryable_after_restart(tmp_path, monkeypatch):
    app, test_client = _client(tmp_path, monkeypatch)
    with test_client as client:
        headers = _login(client, "alice")
        with app.state.session_factory() as db:
            user_id = db.scalar(select(User.id).where(User.username_key == "alice"))
        task = app.state.task_manager.create(TaskSpec(agent="knowledge_agent", goal="Question"),
                                             user_id=user_id)
        app.state.task_manager.transition(task.task_id, "running")
    restarted = create_app(app.state.settings)
    with TestClient(restarted) as client:
        status = client.get(f"/api/v1/agent-tasks/{task.task_id}", headers=headers).json()
        assert status["status"] == "waiting"
        assert any(event["kind"] == "interrupted" for event in status["events"])


def test_required_citations_stop_before_uncited_generation(tmp_path, monkeypatch):
    app, test_client = _client(tmp_path, monkeypatch)
    schema, _ = app.state.tool_registry._tools["rag_search"]
    app.state.tool_registry._tools["rag_search"] = (
        schema, lambda arguments, context: {"context": "", "hits": [], "source_ids": []})
    with test_client as client:
        headers = _login(client, "alice")
        result = client.post("/api/v1/agent-tasks", headers=headers,
                             json={"agent": "knowledge_agent", "goal": "Answer from sources",
                                   "constraints": {"must_cite_sources": True}}).json()
        assert result["status"] == "waiting", result
        assert "没有可核查" in result["error"]


def test_async_task_can_be_polled_to_completion(tmp_path, monkeypatch):
    app, test_client = _client(tmp_path, monkeypatch)
    schema, _ = app.state.tool_registry._tools["diagram_render"]

    def fake_render(arguments, context):
        sleep(.05)
        return {**asdict(build_diagram(arguments.plan, arguments.kind)), "model": "fake-model"}

    app.state.tool_registry._tools["diagram_render"] = (schema, fake_render)
    with test_client as client:
        headers = _login(client, "alice")
        created = client.post("/api/v1/agent-tasks", headers=headers,
                              json={"agent": "diagram_agent", "goal": "Draw", "wait": False,
                                    "inputs": {"kind": "flowchart"}}).json()
        assert created["task_id"]
        for _ in range(40):
            status = client.get(f"/api/v1/agent-tasks/{created['task_id']}", headers=headers).json()
            if status["status"] == "completed":
                break
            sleep(.02)
        assert status["status"] == "completed", status
