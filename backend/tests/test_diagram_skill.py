from app.core.model_preferences import write_preferences
import json
import asyncio
from contextlib import nullcontext
from threading import Event
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.skills.drawing_engine import build_diagram
from app.skills.ai_drawing import edit_diagram, is_edit_request
from app.services.text_generation import TextGenerationError
from app.api.routes import diagrams as diagram_routes
from app.schemas.chat import ChatSend


def test_drawing_stream_emits_running_trace_before_worker_finishes(monkeypatch):
    started = Event()
    release = Event()
    db = SimpleNamespace(rollback=lambda: None)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        task_manager=object(), session_factory=lambda: nullcontext(db))))
    context = (SimpleNamespace(id="user-1"), None)
    payload = ChatSend.model_validate({"content": "画一张流程图",
                                       "skill": {"id": "flowchart", "label": "流程图"}})
    monkeypatch.setattr(diagram_routes, "_owned", lambda *args: None)
    monkeypatch.setattr(diagram_routes, "drawing_trace", lambda manager, task_id, user_id, query: {
        "runId": task_id, "domain": "drawing", "status": "running",
        "stages": [{"id": "live", "kind": "agent", "title": "内容规划 Agent",
                    "status": "running", "summary": "正在规划", "detail": {}}]})

    def blocked_create(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return {"assistantMessage": {"metadata": {"drawingSteps": []}}, "trace": {}}

    monkeypatch.setattr(diagram_routes, "create_diagram", blocked_create)
    response = diagram_routes.stream_diagram("conversation-1", payload, request, db, context)

    async def receive():
        return [json.loads(await anext(response.body_iterator)) for _ in range(4)]

    try:
        events = asyncio.run(receive())
        assert started.is_set()
        assert not release.is_set()
        assert events[2]["type"] == "trace"
        assert events[2]["trace"]["stages"][0]["status"] == "running"
    finally:
        release.set()


def test_diagram_skill_generates_saves_and_restores(tmp_path, monkeypatch):
    env = tmp_path / "models.json"
    write_preferences(env, {'providers': {'deepseek': {'name': 'deepseek', 'runtimeProvider': 'deepseek', 'apiKey': 'test-key', 'configs': {'text': {'baseUrl': 'https://api.deepseek.com', 'model': 'deepseek-flash'}}}}, 'active': {'text': 'deepseek'}})
    for name in ("PROVIDER", "BASE_URL", "MODEL", "API_KEY"):
        monkeypatch.delenv(f"MINDPILOT_TEXT_{name}", raising=False)
    settings = Settings(database_url=f"sqlite:///{(tmp_path / 'draw.db').as_posix()}",
                        jwt_secret="test-secret-longer-than-thirty-two-bytes-for-jwt",
                        allowed_origins=("http://localhost:5173",), model_config_path=env, data_dir=tmp_path / "data")
    plan = {"nodes": [{"id": "start", "label": "开始", "kind": "start"},
                      {"id": "service", "label": "业务服务层", "kind": "process"}],
            "edges": [{"source": "start", "target": "service"}], "groups": []}
    edit_requests = []

    def fake_model(config, messages):
        if "精确编辑器" in messages[0]["content"]:
            edit_requests.append(messages)
            return (json.dumps({"operations": [{"op": "rename", "target_id": "service",
                                                "label": "核心业务层"}]}, ensure_ascii=False),
                    {"model": config.model})
        return json.dumps(plan, ensure_ascii=False), {"model": config.model}

    monkeypatch.setattr("app.skills.ai_drawing.complete_text", fake_model)
    with TestClient(create_app(settings)) as client:
        client.post("/api/v1/auth/register", json={"username": "alice", "password": "strong-password-123"})
        token = client.post("/api/v1/auth/login", json={"username": "alice", "password": "strong-password-123"}).json()["accessToken"]
        headers = {"Authorization": f"Bearer {token}"}
        conversation = client.post("/api/v1/conversations", headers=headers, json={"title": "新会话"}).json()
        base = f"/api/v1/conversations/{conversation['id']}"
        response = client.post(f"{base}/diagrams", headers=headers,
                               json={"content": "画一个业务流程", "skill": {"id": "flowchart", "label": "流程图"}})
        assert response.status_code == 200, response.text
        item = response.json()["assistantMessage"]
        assert item["metadata"]["diagram"]["type"] == "flowchart"
        assert "业务服务层" in item["metadata"]["diagram"]["svg"]
        assert "mxGraphModel" in item["metadata"]["diagram"]["xml"]
        assert response.json()["trace"]["domain"] == "drawing"
        titles = [stage["title"] for stage in response.json()["trace"]["stages"]]
        assert titles.index("分析绘图需求") < titles.index("主 Agent · 任务调度")
        assert titles.index("进入绘图功能域") < titles.index("内容规划 Agent")
        assert not any(stage["kind"] == "skill" for stage in response.json()["trace"]["stages"])
        supervisor_stage = next(stage for stage in response.json()["trace"]["stages"]
                                if stage["title"] == "主 Agent · 任务调度")
        domain_stage = next(stage for stage in response.json()["trace"]["stages"]
                            if stage["title"] == "进入绘图功能域")
        assert supervisor_stage["durationMs"] > 0
        assert domain_stage["status"] == "ok" and "durationMs" not in domain_stage
        assert "工具调用 · diagram_render" in titles
        assert len(item["metadata"]["drawingSteps"]) == 4
        assert item["metadata"]["drawingSteps"][1]["kind"] == "nodes"
        assert item["metadata"]["drawingSteps"][1]["count"] == 2
        assert item["metadata"]["drawingSteps"][2]["items"][0]["source"] == "开始"
        trace = client.get(
            f"/api/v1/agent-tasks/{item['metadata']['agentTaskId']}/trace", headers=headers).json()
        purposes = {event["detail"]["purpose"] for event in trace["events"]
                    if event["kind"] == "model_request"}
        assert purposes == {"drawing_content", "drawing_layout", "drawing_review"}
        assert sum(event["kind"] == "model_response" for event in trace["events"]) == 3

        turn_url = f"{base}/messages/{item['id']}/diagram/turns"
        # Real draw.io exports commonly exceed the default 16 KB artifact read.
        # A valid large draft must reach the editor intact.
        large_xml = item["metadata"]["diagram"]["xml"] + " " * 18000
        first = client.post(turn_url, headers=headers, json={
            "content": "把业务服务层的背景改为红色",
            "xml": large_xml, "baseVersion": 1})
        assert first.status_code == 200, first.text
        first_diagram = first.json()["message"]["metadata"]["diagram"]
        assert "#FBE4E5" in first_diagram["xml"]
        assert first_diagram["version"] == 2
        second = client.post(turn_url, headers=headers, json={
            "content": "把业务服务层的背景改为蓝色",
            "xml": first_diagram["xml"], "baseVersion": 2})
        assert second.status_code == 200, second.text
        second_message = second.json()["message"]
        assert "#E5EDFF" in second_message["metadata"]["diagram"]["xml"]
        assert len(second_message["metadata"]["editorTurns"]) == 4
        third = client.post(turn_url, headers=headers, json={
            "content": "把业务服务层名称改为核心业务层",
            "xml": second_message["metadata"]["diagram"]["xml"], "baseVersion": 3})
        assert third.status_code == 200, third.text
        assert "核心业务层" in third.json()["message"]["metadata"]["diagram"]["xml"]
        assert edit_requests and "背景改为红色" in edit_requests[0][1]["content"]
        assert client.post(turn_url, headers=headers, json={
            "content": "把业务服务层的背景改为红色",
            "xml": item["metadata"]["diagram"]["xml"], "baseVersion": 1}).status_code == 409
        restored_turn = client.get(f"{base}/messages", headers=headers).json()["items"]
        assert next(row for row in restored_turn if row["id"] == item["id"])["metadata"]["editorTurns"] == third.json()["message"]["metadata"]["editorTurns"]

        streamed = client.post(f"{base}/diagrams/stream", headers=headers,
                               json={"content": "再画一个流程", "skill": {"id": "flowchart", "label": "流程图"}})
        assert streamed.status_code == 200, streamed.text
        events = [json.loads(line) for line in streamed.text.splitlines() if line]
        assert [event["type"] for event in events[:2]] == ["progress", "progress"]
        traces = [event["trace"] for event in events if event["type"] == "trace"]
        assert len(traces) >= 2
        assert traces[0]["status"] == "running"
        assert any(any(stage["title"] == "内容规划 Agent" for stage in trace["stages"])
                   for trace in traces)
        assert events[-1]["type"] == "done"
        assert events[-1]["assistantMessage"]["metadata"]["drawingSteps"][1]["title"] == "内容规划 · 节点与信息"

        changed_by_chat = client.post(f"{base}/diagrams", headers=headers,
                                      json={"content": "把业务服务层的背景改为红色",
                                            "skill": {"id": "flowchart", "label": "流程图"}})
        assert changed_by_chat.status_code == 200, changed_by_chat.text
        assert "#FBE4E5" in changed_by_chat.json()["assistantMessage"]["metadata"]["diagram"]["xml"]

        mindmap = client.post(f"{base}/diagrams", headers=headers,
                              json={"content": "画一个业务知识思维导图",
                                    "skill": {"id": "mindmap", "label": "思维导图"}})
        assert mindmap.status_code == 200, mindmap.text
        assert mindmap.json()["assistantMessage"]["metadata"]["diagram"]["type"] == "mindmap"

        xml = build_diagram({"nodes": [{"id": "changed", "label": "已调整", "kind": "process"}],
                             "edges": [], "groups": []}, "flowchart").xml
        saved = client.put(f"{base}/messages/{item['id']}/diagram", headers=headers,
                           json={"xml": xml, "baseVersion": 4})
        assert saved.status_code == 200, saved.text
        assert saved.json()["metadata"]["diagram"]["version"] == 5
        saved_artifact_id = saved.json()["metadata"]["diagram"]["artifactId"]
        assert saved_artifact_id != item["metadata"]["diagram"]["artifactId"]
        assert client.get(f"/api/v1/agent-artifacts/{saved_artifact_id}", headers=headers).text == xml
        stored = client.get(f"{base}/messages", headers=headers).json()["items"]
        saved_stored = next(row for row in stored if row["id"] == item["id"])
        assert saved_stored["metadata"]["diagram"]["xml"] == xml
        assert "已调整" in saved_stored["metadata"]["diagram"]["svg"]
        streamed_stored = next(row for row in stored if row["id"] == events[-1]["assistantMessage"]["id"])
        assert len(streamed_stored["metadata"]["drawingSteps"]) == 4
        assert client.put(f"{base}/messages/{item['id']}/diagram", headers=headers,
                          json={"xml": "<not-diagram/>"}).status_code == 422

        client.post("/api/v1/auth/register", json={"username": "bob", "password": "strong-password-123"})
        bob = client.post("/api/v1/auth/login", json={"username": "bob", "password": "strong-password-123"}).json()["accessToken"]
        assert client.put(f"{base}/messages/{item['id']}/diagram", headers={"Authorization": f"Bearer {bob}"},
                          json={"xml": xml}).status_code == 404


def test_failed_drawing_stream_exposes_and_persists_runtime_trace(tmp_path, monkeypatch):
    env = tmp_path / "models.json"
    write_preferences(env, {'providers': {'deepseek': {'name': 'deepseek', 'runtimeProvider': 'deepseek', 'apiKey': 'test-key', 'configs': {'text': {'baseUrl': 'https://api.deepseek.com', 'model': 'deepseek-flash'}}}}, 'active': {'text': 'deepseek'}})
    for name in ("PROVIDER", "BASE_URL", "MODEL", "API_KEY"):
        monkeypatch.delenv(f"MINDPILOT_TEXT_{name}", raising=False)
    settings = Settings(database_url=f"sqlite:///{(tmp_path / 'failed-draw.db').as_posix()}",
                        jwt_secret="test-secret-longer-than-thirty-two-bytes-for-jwt",
                        allowed_origins=("http://localhost:5173",), model_config_path=env, data_dir=tmp_path / "data")

    def timeout_model(config, messages):
        raise TextGenerationError("DeepSeek 响应超时，请稍后重试")

    monkeypatch.setattr("app.skills.ai_drawing.complete_text", timeout_model)
    with TestClient(create_app(settings)) as client:
        client.post("/api/v1/auth/register", json={"username": "alice", "password": "strong-password-123"})
        token = client.post("/api/v1/auth/login", json={"username": "alice", "password": "strong-password-123"}).json()["accessToken"]
        headers = {"Authorization": f"Bearer {token}"}
        conversation = client.post("/api/v1/conversations", headers=headers,
                                   json={"title": "新会话"}).json()
        base = f"/api/v1/conversations/{conversation['id']}"
        response = client.post(f"{base}/diagrams/stream", headers=headers,
                               json={"content": "画一张思维导图",
                                     "skill": {"id": "mindmap", "label": "思维导图"}})
        events = [json.loads(line) for line in response.text.splitlines() if line]
        failed = events[-1]
        assert failed["type"] == "error"
        assert failed["taskId"]
        assert failed["trace"]["status"] == "error"
        assert any(stage["kind"] == "model" and stage["status"] == "error"
                   for stage in failed["trace"]["stages"])
        saved = client.get(f"{base}/agent-runs/latest", headers=headers).json()
        assert saved["trace"]["runId"] == failed["taskId"]


def test_broad_edit_uses_configured_model_and_graph_connections(tmp_path, monkeypatch):
    env = tmp_path / "models.json"
    write_preferences(env, {'providers': {'deepseek': {'name': 'deepseek', 'runtimeProvider': 'deepseek', 'apiKey': 'test-key', 'configs': {'text': {'baseUrl': 'https://api.deepseek.com', 'model': 'chosen-diagram-model'}}}}, 'active': {'text': 'deepseek'}})
    for name in ("PROVIDER", "BASE_URL", "MODEL", "API_KEY"):
        monkeypatch.delenv(f"MINDPILOT_TEXT_{name}", raising=False)
    xml = build_diagram({"nodes": [{"id": "start", "label": "开始", "kind": "start"},
                                  {"id": "review", "label": "审核", "kind": "process"}],
                         "edges": [{"source": "start", "target": "review"}], "groups": []}, "flowchart").xml
    requests = []

    def fake_model(config, messages):
        requests.append((config.model, messages))
        return (json.dumps({"operations": [{"op": "rename", "target_id": "review",
                                            "label": "审核并记录结果"}]}, ensure_ascii=False),
                {"model": config.model})

    assert is_edit_request("重新完善一下")
    result = edit_diagram("重新完善一下", xml, model_config_path=env, complete_fn=fake_model)
    assert result["model"] == "chosen-diagram-model"
    assert "审核并记录结果" in result["xml"]
    assert '"source": "start"' in requests[0][1][0]["content"]
    assert '"target": "review"' in requests[0][1][0]["content"]
