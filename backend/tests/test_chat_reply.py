from app.core.model_preferences import write_preferences
import json

from fastapi.testclient import TestClient
import httpx

from app.core.config import Settings
from app.core.model_runtime import RuntimeModel
from app.main import create_app
from app.services import text_generation


def test_deepseek_request_uses_server_side_key_and_model(monkeypatch):
    observed = {}

    def respond(request):
        observed["url"] = str(request.url)
        observed["authorization"] = request.headers["Authorization"]
        observed["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "你好"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        })

    original_client = httpx.Client
    monkeypatch.setattr(text_generation.httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(respond), **kwargs
    ))
    config = RuntimeModel("text", "deepseek", "https://api.deepseek.com", "deepseek-flash", "private-key")
    answer, meta = text_generation.complete_text(config, [{"role": "user", "content": "你好"}])
    assert answer == "你好"
    assert observed == {
        "url": "https://api.deepseek.com/chat/completions",
        "authorization": "Bearer private-key",
        "body": {"model": "deepseek-flash", "messages": [{"role": "user", "content": "你好"}], "stream": False},
    }
    assert meta["tokens"] == {"input": 3, "output": 2}


def test_deepseek_stream_parses_delta_and_usage_chunk(monkeypatch):
    observed = {}

    def respond(request):
        observed["body"] = json.loads(request.content)
        lines = [
            'data: {"choices":[{"delta":{"content":"你好"}}]}',
            'data: {"choices":[],"usage":{"completion_tokens":2}}',
            'data: [DONE]',
        ]
        return httpx.Response(200, text="\n\n".join(lines) + "\n\n")

    original_client = httpx.Client
    monkeypatch.setattr(text_generation.httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(respond), **kwargs
    ))
    config = RuntimeModel("text", "deepseek", "https://api.deepseek.com", "deepseek-flash", "private-key")
    stream = text_generation.stream_text(config, [{"role": "user", "content": "你好"}])
    assert next(stream) == "你好"
    try:
        next(stream)
        assert False, "stream should finish"
    except StopIteration as done:
        assert done.value["tokens"] == {"input": 0, "output": 2}
    assert observed["body"]["stream"] is True
    assert observed["body"]["stream_options"] == {"include_usage": True}


def test_chat_reply_uses_env_model_and_persists_real_answer(tmp_path, monkeypatch):
    env_path = tmp_path / "models.json"
    write_preferences(env_path, {'providers': {'deepseek': {'name': 'deepseek', 'runtimeProvider': 'deepseek', 'apiKey': 'private-test-key', 'configs': {'text': {'baseUrl': 'https://api.deepseek.com', 'model': 'deepseek-flash'}}}}, 'active': {'text': 'deepseek'}})
    for field in ("PROVIDER", "BASE_URL", "MODEL", "API_KEY"):
        monkeypatch.delenv(f"MINDPILOT_TEXT_{field}", raising=False)
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        jwt_secret="test-secret-longer-than-thirty-two-bytes-for-jwt",
        allowed_origins=("http://localhost:5173",),
        model_config_path=env_path,
    )
    calls = []

    def fake_complete(config, messages):
        calls.append((config, messages))
        return "这是 DeepSeek 的回答", {"model": config.model, "latencyMs": 42, "tokens": {"input": 12, "output": 9}}

    monkeypatch.setattr("app.api.routes.conversations.complete_text", fake_complete)
    with TestClient(create_app(settings)) as client:
        client.post("/api/v1/auth/register", json={"username": "alice", "password": "strong-password-123"})
        token = client.post("/api/v1/auth/login", json={"username": "alice", "password": "strong-password-123"}).json()["accessToken"]
        headers = {"Authorization": f"Bearer {token}"}
        conversation = client.post("/api/v1/conversations", headers=headers, json={"title": "新会话"}).json()
        path = f"/api/v1/conversations/{conversation['id']}/reply"
        first = client.post(path, headers=headers, json={"content": "你好", "model": "user-chosen-model"})
        assert first.status_code == 200, first.text
        assert first.json()["assistantMessage"]["content"] == "这是 DeepSeek 的回答"
        assert first.json()["assistantMessage"]["metadata"]["model"] == "deepseek-flash"
        trace = client.get(f"/api/v1/conversations/{conversation['id']}/agent-runs/latest", headers=headers).json()["trace"]
        assert trace["status"] == "ok"
        assert [stage["kind"] for stage in trace["stages"]] == ["input", "agent", "retrieval", "model", "output"]
        assert all(stage["durationMs"] > 0 for stage in trace["stages"][:-1])
        assert "private-test-key" not in first.text
        assert calls[0][0].model == "deepseek-flash"
        assert calls[0][1][-1] == {"role": "user", "content": "你好"}

        second = client.post(path, headers=headers, json={"content": "继续"})
        assert second.status_code == 200
        assert [item["role"] for item in calls[1][1][-3:]] == ["user", "assistant", "user"]
        stored = client.get(f"/api/v1/conversations/{conversation['id']}/messages", headers=headers).json()["items"]
        assert [item["content"] for item in stored] == ["你好", "这是 DeepSeek 的回答", "继续", "这是 DeepSeek 的回答"]
        assert "private-test-key" not in str(stored)

        unsupported = client.post(path, headers=headers, json={"content": "看这个", "attachmentIds": ["fake"]})
        assert unsupported.status_code == 400
        assert len(client.get(f"/api/v1/conversations/{conversation['id']}/messages", headers=headers).json()["items"]) == 4

        client.post("/api/v1/auth/register", json={"username": "bob", "password": "strong-password-123"})
        bob = client.post("/api/v1/auth/login", json={"username": "bob", "password": "strong-password-123"}).json()["accessToken"]
        assert client.post(path, headers={"Authorization": f"Bearer {bob}"}, json={"content": "越权"}).status_code == 404


def test_chat_reply_needs_configured_key(tmp_path, monkeypatch):
    for field in ("PROVIDER", "BASE_URL", "MODEL", "API_KEY"):
        monkeypatch.delenv(f"MINDPILOT_TEXT_{field}", raising=False)
    env_path = tmp_path / "models.json"
    write_preferences(env_path, {'providers': {'openai': {'name': 'openai', 'runtimeProvider': 'openai', 'apiKey': 'CHANGE_ME', 'configs': {'text': {'baseUrl': 'https://api.deepseek.com', 'model': 'deepseek-flash'}}}}, 'active': {'text': 'openai'}})
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        jwt_secret="test-secret-longer-than-thirty-two-bytes-for-jwt",
        allowed_origins=("http://localhost:5173",),
        model_config_path=env_path,
    )
    with TestClient(create_app(settings)) as client:
        client.post("/api/v1/auth/register", json={"username": "alice", "password": "strong-password-123"})
        token = client.post("/api/v1/auth/login", json={"username": "alice", "password": "strong-password-123"}).json()["accessToken"]
        headers = {"Authorization": f"Bearer {token}"}
        conversation = client.post("/api/v1/conversations", headers=headers, json={"title": "新会话"}).json()
        reply = client.post(f"/api/v1/conversations/{conversation['id']}/reply", headers=headers, json={"content": "你好"})
        assert reply.status_code == 503
        assert "尚未" in reply.json()["detail"]
        assert client.get(f"/api/v1/conversations/{conversation['id']}/messages", headers=headers).json()["items"] == []


def test_streaming_voice_reply_persists_complete_exchange(tmp_path, monkeypatch):
    env_path = tmp_path / "models.json"
    write_preferences(env_path, {'providers': {'deepseek': {'name': 'deepseek', 'runtimeProvider': 'deepseek', 'apiKey': 'private-test-key', 'configs': {'text': {'baseUrl': 'https://api.deepseek.com', 'model': 'deepseek-flash'}}}}, 'active': {'text': 'deepseek'}})
    for field in ("PROVIDER", "BASE_URL", "MODEL", "API_KEY"):
        monkeypatch.delenv(f"MINDPILOT_TEXT_{field}", raising=False)
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        jwt_secret="test-secret-longer-than-thirty-two-bytes-for-jwt",
        allowed_origins=("http://localhost:5173",), model_config_path=env_path, data_dir=tmp_path,
    )
    seen = {}

    def fake_stream(config, messages):
        seen["calls"] = seen.get("calls", 0) + 1
        seen["model"] = config.model
        seen["system"] = messages[0]["content"]
        seen["messages"] = messages
        seen["last"] = messages[-1]
        if seen["calls"] == 3:
            yield "这是重新生成的回答。"
        else:
            yield "您好，"
            yield "有什么可以帮您？"

    monkeypatch.setattr("app.api.routes.conversations.stream_text", fake_stream)
    monkeypatch.setattr("app.api.routes.files.upload_image", lambda config, filename, mime_type, data: {
        "id": "file-api-test-image", "name": filename, "bytes": len(data), "mimeType": mime_type,
    })
    with TestClient(create_app(settings)) as client:
        client.post("/api/v1/auth/register", json={"username": "alice", "password": "strong-password-123"})
        token = client.post("/api/v1/auth/login", json={"username": "alice", "password": "strong-password-123"}).json()["accessToken"]
        headers = {"Authorization": f"Bearer {token}"}
        conversation = client.post("/api/v1/conversations", headers=headers, json={"title": "新会话"}).json()
        path = f"/api/v1/conversations/{conversation['id']}/reply/stream"
        messages_path = f"/api/v1/conversations/{conversation['id']}/messages"
        session_id = "voice-test-session"
        marker = client.post(messages_path, headers=headers, json={
            "role": "system", "content": "实时通话",
            "metadata": {"type": "realtime_marker", "realtimeSessionId": session_id},
        })
        assert marker.status_code == 201
        greeting = client.post(messages_path, headers=headers, json={
            "role": "assistant", "content": "我是你的 智能知识管家思雅。",
            "metadata": {"realtime": True, "realtimeSessionId": session_id},
        })
        assert greeting.status_code == 201
        assert client.post(path, json={"content": "您好"}).status_code == 401
        response = client.post(path, headers=headers, json={
            "content": "您好", "voiceMode": True, "realtimeSessionId": session_id, "streamId": "live-test-stream",
        })
        assert response.status_code == 200, response.text
        events = [json.loads(line) for line in response.text.splitlines()]
        answer_events = [event for event in events if event["type"] in {"delta", "done"}]
        assert [event["type"] for event in answer_events] == ["delta", "delta", "done"]
        assert "".join(event["text"] for event in answer_events[:-1]) == "您好，有什么可以帮您？"
        assert events[-1]["assistantMessage"]["content"] == "您好，有什么可以帮您？"
        assert seen["model"] == "deepseek-flash"
        assert "始终用简体中文回答" in seen["system"]
        assert seen["last"] == {"role": "user", "content": "您好"}
        stored = client.get(messages_path, headers=headers).json()["items"]
        assert [item["content"] for item in stored] == [
            "实时通话", "我是你的 智能知识管家思雅。", "您好", "您好，有什么可以帮您？",
        ]
        assert all(item["metadata"].get("realtimeSessionId") == session_id for item in stored)
        assert "private-test-key" not in response.text

        work = client.post(path, headers=headers, json={
            "content": "整理成步骤", "skill": {
                "id": "flowchart", "label": "流程图", "systemPrompt": "请按流程步骤组织回答。",
            },
        })
        assert work.status_code == 200, work.text
        assert "用用户的语言回答" in seen["system"]
        assert seen["messages"][1] == {"role": "system", "content": "请按流程步骤组织回答。"}
        work_events = [json.loads(line) for line in work.text.splitlines()]
        assert work_events[-1]["type"] == "done"
        assert work_events[-1]["userMessage"]["metadata"]["skill"]["id"] == "flowchart"
        stored = client.get(messages_path, headers=headers).json()["items"]
        assert len(stored) == 6
        original_user_id = stored[-2]["id"]
        original_assistant_id = stored[-1]["id"]
        regeneration = client.post(path, headers=headers, json={
            "content": "这不是原问题", "regenerateMessageId": original_assistant_id,
        })
        assert regeneration.status_code == 200, regeneration.text
        regenerated_events = [json.loads(line) for line in regeneration.text.splitlines()]
        assert seen["last"] == {"role": "user", "content": "整理成步骤"}
        assert regenerated_events[-1]["assistantMessage"]["id"] == original_assistant_id
        assert regenerated_events[-1]["userMessage"]["id"] == original_user_id
        regenerated_messages = client.get(messages_path, headers=headers).json()["items"]
        assert len(regenerated_messages) == 6
        assert regenerated_messages[-1]["content"] == "这是重新生成的回答。"
        assert regenerated_events[-1]["regenerationMode"] == "replace"

        earlier_user_id = regenerated_messages[2]["id"]
        earlier_assistant_id = regenerated_messages[3]["id"]
        earlier_answer = regenerated_messages[3]["content"]
        historical = client.post(path, headers=headers, json={
            "content": "这不是原问题", "regenerateMessageId": earlier_assistant_id,
        })
        assert historical.status_code == 200, historical.text
        historical_events = [json.loads(line) for line in historical.text.splitlines()]
        assert historical_events[-1]["regenerationMode"] == "append"
        assert seen["last"] == {"role": "user", "content": "您好"}
        assert historical_events[-1]["userMessage"]["id"] != earlier_user_id
        assert historical_events[-1]["assistantMessage"]["id"] != earlier_assistant_id
        historical_messages = client.get(messages_path, headers=headers).json()["items"]
        assert len(historical_messages) == 8
        assert historical_messages[3]["content"] == earlier_answer
        assert historical_messages[-2]["content"] == "您好"
        assert historical_messages[-1]["id"] == historical_events[-1]["assistantMessage"]["id"]
        text_reply = client.post(path, headers=headers, json={
            "content": "解释附件", "textAttachments": [{"name": "notes.txt", "content": "附件中的事实：苹果是红色的。", "mimeType": "text/plain"}],
        })
        assert text_reply.status_code == 200, text_reply.text
        assert "附件中的事实：苹果是红色的。" in seen["last"]["content"]
        text_messages = client.get(messages_path, headers=headers).json()["items"]
        assert text_messages[-2]["content"] == "解释附件"
        assert text_messages[-2]["metadata"]["attachments"][0]["name"] == "notes.txt"
        assert text_messages[-2]["metadata"]["attachments"][0]["content"] == "附件中的事实：苹果是红色的。"
        followup = client.post(path, headers=headers, json={"content": "附件说了什么？"})
        assert followup.status_code == 200, followup.text
        assert any("附件中的事实：苹果是红色的。" in str(item["content"]) for item in seen["messages"])
        uploaded_image = client.post("/api/v1/files", headers=headers,
                                     files={"file": ("image.png", b"test-image-bytes", "image/png")})
        assert uploaded_image.status_code == 201, uploaded_image.text
        preview_id = uploaded_image.json()["previewId"]
        preview_path = f"/api/v1/files/previews/{preview_id}"
        assert client.get(preview_path).status_code == 401
        preview = client.get(preview_path, headers=headers)
        assert preview.status_code == 200
        assert preview.content == b"test-image-bytes"
        assert preview.headers["content-type"] == "image/png"
        image_reply = client.post(path, headers=headers, json={
            "content": "", "attachmentIds": ["file-api-test-image"],
            "attachmentNames": ["image.png"], "attachmentPreviewIds": [preview_id],
        })
        assert image_reply.status_code == 200, image_reply.text
        assert seen["last"] == {"role": "user", "content": [{"type": "file", "file_id": "file-api-test-image"}]}
        image_messages = client.get(messages_path, headers=headers).json()["items"]
        assert image_messages[-2]["content"] == ""
        assert image_messages[-2]["metadata"]["attachments"][0]["name"] == "image.png"
        assert image_messages[-2]["metadata"]["attachments"][0]["previewId"] == preview_id
        assert client.post(path, headers=headers, json={"content": ""}).status_code == 422
        assert client.post(path, headers=headers, json={"content": "任意", "regenerateMessageId": "missing"}).status_code == 404
        ending = client.post(messages_path, headers=headers, json={
            "role": "system", "content": "实时通话结束",
            "metadata": {"type": "realtime_marker", "realtimeSessionId": session_id},
        })
        assert ending.status_code == 201
        stored = client.get(messages_path, headers=headers).json()["items"]
        assert stored[0]["content"] == "实时通话"
        assert stored[-1]["content"] == "实时通话结束"
