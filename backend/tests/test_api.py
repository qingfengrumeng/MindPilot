from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def client_for(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        jwt_secret="test-secret-longer-than-thirty-two-bytes-for-jwt",
        allowed_origins=("http://localhost:5173",),
        data_dir=tmp_path / "data",
        model_config_path=tmp_path / ".mindpoilt" / "models.json",
    )
    return TestClient(create_app(settings))


def register(client, username="alice", password="strong-password-123"):
    return client.post("/api/v1/auth/register", json={"username": username, "password": password})


def login(client, username="alice", password="strong-password-123"):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_auth_session_rotation_and_revocation(tmp_path):
    with client_for(tmp_path) as client:
        assert register(client).status_code == 201
        assert register(client, username="ALICE").status_code == 409
        assert login(client, password="wrong-password").status_code == 401
        signed_in = login(client)
        assert signed_in.status_code == 200
        access = signed_in.json()["accessToken"]
        old_refresh = client.cookies.get("mindpilot_refresh")
        assert client.get("/api/v1/auth/me", headers=headers(access)).json()["username"] == "alice"
        from app.db.models import User
        from sqlalchemy import select
        with client.app.state.session_factory() as db:
            assert db.scalar(select(User).where(User.username_key == "alice")).password_hash != "strong-password-123"
        rotated = client.post("/api/v1/auth/refresh")
        assert rotated.status_code == 200
        assert client.cookies.get("mindpilot_refresh") != old_refresh
        assert client.post("/api/v1/auth/refresh", cookies={"mindpilot_refresh": old_refresh}).status_code == 401
        assert client.post("/api/v1/auth/logout", headers=headers(access)).status_code == 204
        assert client.get("/api/v1/auth/me", headers=headers(access)).status_code == 401
        assert client.post("/api/v1/auth/refresh").status_code == 401


def test_conversations_persist_and_are_private(tmp_path):
    with client_for(tmp_path) as client:
        register(client)
        alice = login(client).json()["accessToken"]
        created = client.post("/api/v1/conversations", headers=headers(alice), json={"title": "新会话"})
        assert created.status_code == 201
        assert created.json()["taskId"] == "general"
        conversation_id = created.json()["id"]
        message = client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers=headers(alice), json={"content": "你好", "metadata": {"skill": {"id": "x"}}},
        )
        assert message.status_code == 201
        assert client.get("/api/v1/conversations", headers=headers(alice)).json()["items"][0]["messages"] == 1
        register(client, username="bob")
        bob = login(client, username="bob").json()["accessToken"]
        assert client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=headers(bob)).status_code == 404
        assert client.delete(f"/api/v1/conversations/{conversation_id}/messages/{message.json()['id']}", headers=headers(bob)).status_code == 404
        assert client.patch(f"/api/v1/conversations/{conversation_id}", headers=headers(bob), json={"pinned": True}).status_code == 404
        assert client.delete(f"/api/v1/conversations/{conversation_id}", headers=headers(bob)).status_code == 404

    with client_for(tmp_path) as client:
        alice = login(client).json()["accessToken"]
        stored = client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=headers(alice)).json()["items"]
        assert stored[0]["content"] == "你好"
        assert stored[0]["metadata"]["skill"]["id"] == "x"
        assert stored[0]["createdAt"].endswith("Z")
        assert client.delete(f"/api/v1/conversations/{conversation_id}/messages/{stored[0]['id']}", headers=headers(alice)).status_code == 204
        assert client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=headers(alice)).json()["items"] == []


def test_password_change_revokes_all_sessions(tmp_path):
    with client_for(tmp_path) as client:
        register(client)
        first = login(client).json()["accessToken"]
        second = login(client).json()["accessToken"]
        changed = client.post("/api/v1/auth/change-password", headers=headers(first), json={"currentPassword": "strong-password-123", "nextPassword": "another-long-password"})
        assert changed.status_code == 204
        assert client.get("/api/v1/auth/me", headers=headers(first)).status_code == 401
        assert client.get("/api/v1/auth/me", headers=headers(second)).status_code == 401
        assert login(client).status_code == 401
        assert login(client, password="another-long-password").status_code == 200


def test_personal_profile_avatar_and_statistics_are_private(tmp_path):
    from datetime import timedelta
    from app.core.security import utcnow
    from app.db.models import Message

    with client_for(tmp_path) as client:
        register(client)
        access = headers(login(client).json()["accessToken"])
        avatar = "data:image/png;base64,aGVsbG8="
        updated = client.patch("/api/v1/auth/me", headers=access,
                               json={"displayName": "  Alice 自己  ", "avatar": avatar})
        assert updated.status_code == 200
        assert updated.json()["displayName"] == "Alice 自己"
        assert client.get("/api/v1/auth/me", headers=access).json()["avatar"] == avatar
        assert client.patch("/api/v1/auth/me", headers=access, json={"avatar": "javascript:alert(1)"}).status_code == 422
        assert client.patch("/api/v1/auth/me", headers=access, json={"displayName": "   "}).status_code == 422
        conversation = client.post("/api/v1/conversations", headers=access, json={"title": "测试"}).json()
        path = f"/api/v1/conversations/{conversation['id']}/messages"
        for index in range(2):
            question = client.post(path, headers=access, json={"content": "问题", "metadata": {
                "skill": {"id": "mindmap", "label": "思维导图"}}}).json()
            with client.app.state.session_factory() as db:
                db.get(Message, question["id"]).created_at = utcnow() - timedelta(days=index)
                db.commit()
            assert client.post(path, headers=access, json={"role": "assistant", "content": "回答", "metadata": {
                "tokens": {"input": 100, "output": 25}, "latencyMs": 1200,
                "toolCalls": [{"tool": "draw"}]}}).status_code == 201
        client.post(path, headers=access, json={"role": "assistant", "content": "无用量"})
        stats = client.get("/api/v1/auth/me/statistics", headers=access).json()
        assert stats["totalTokens"] == 250
        assert stats["inputTokens"] == 200 and stats["outputTokens"] == 50
        assert stats["peakTokens"] == 125 and stats["longestTaskMs"] == 1200
        assert stats["conversationCount"] == 1 and stats["messageCount"] == 2
        assert stats["longestStreak"] == 2 and stats["currentStreak"] == 2
        assert stats["featureCallCount"] == 2 and stats["toolCallCount"] == 2
        assert stats["missingUsageCount"] == 1
        assert stats["features"] == [{"id": "mindmap", "label": "思维导图", "count": 2}]
        register(client, username="bob")
        bob = headers(login(client, username="bob").json()["accessToken"])
        assert client.get("/api/v1/auth/me/statistics", headers=bob).json()["totalTokens"] == 0
        assert client.get("/api/v1/auth/me", headers=bob).json()["avatar"] == ""
        assert client.get("/api/v1/auth/me/statistics").status_code == 401

    with client_for(tmp_path) as client:
        access = headers(login(client).json()["accessToken"])
        assert client.get("/api/v1/auth/me", headers=access).json()["avatar"] == avatar
        assert client.get("/api/v1/auth/me/statistics", headers=access).json()["totalTokens"] == 250


def test_conversation_activity_uses_latest_turn_not_metadata_updates(tmp_path):
    from datetime import datetime, timedelta, timezone

    from app.db.models import Message

    with client_for(tmp_path) as client:
        register(client)
        access = headers(login(client).json()["accessToken"])
        created = client.post("/api/v1/conversations", headers=access, json={"title": "任务"}).json()
        assert created["lastMessageAt"] is None
        path = f"/api/v1/conversations/{created['id']}"
        start = datetime(2025, 1, 1, 8, tzinfo=timezone.utc)
        message_ids = []
        for role in ("user", "assistant", "system"):
            response = client.post(f"{path}/messages", headers=access,
                                   json={"role": role, "content": role})
            assert response.status_code == 201
            message_ids.append(response.json()["id"])
        with client.app.state.session_factory() as db:
            for index, message_id in enumerate(message_ids):
                db.get(Message, message_id).created_at = start + timedelta(minutes=index)
            db.commit()

        listed = client.get("/api/v1/conversations", headers=access).json()["items"][0]
        assert listed["messages"] == 3
        assert listed["lastMessageAt"] == "2025-01-01T08:01:00Z"
        updated = client.patch(path, headers=access, json={"title": "改名", "pinned": True}).json()
        assert updated["lastMessageAt"] == listed["lastMessageAt"]
        assert updated["updatedAt"] != updated["lastMessageAt"]

        assert client.delete(f"{path}/messages/{message_ids[1]}", headers=access).status_code == 204
        listed = client.get("/api/v1/conversations", headers=access).json()["items"][0]
        assert listed["lastMessageAt"] == "2025-01-01T08:00:00Z"
        assert client.delete(f"{path}/messages/{message_ids[0]}", headers=access).status_code == 204
        listed = client.get("/api/v1/conversations", headers=access).json()["items"][0]
        assert listed["lastMessageAt"] is None
        assert listed["createdAt"] == created["createdAt"]


def test_profile_session_management_and_login_throttle(tmp_path):
    with client_for(tmp_path) as client:
        register(client)
        for _ in range(5):
            assert login(client, password="incorrect-password").status_code == 401
        assert login(client).status_code == 429

        register(client, username="bob")
        bob = login(client, username="bob").json()["accessToken"]
        updated = client.patch("/api/v1/auth/me", headers=headers(bob), json={"displayName": "Bob", "researchField": "RAG"})
        assert updated.status_code == 200
        assert updated.json()["displayName"] == "Bob"
        assert updated.json()["researchField"] == "RAG"
        sessions = client.get("/api/v1/auth/sessions", headers=headers(bob)).json()["items"]
        assert len(sessions) == 1 and sessions[0]["current"]
        assert client.delete(f"/api/v1/auth/sessions/{sessions[0]['id']}", headers=headers(bob)).status_code == 204
        assert client.get("/api/v1/auth/me", headers=headers(bob)).status_code == 401


def test_disallowed_origin_and_unauthenticated_access(tmp_path):
    with client_for(tmp_path) as client:
        assert client.get("/api/v1/conversations").status_code == 401
        response = client.post("/api/v1/auth/register", headers={"Origin": "https://untrusted.example"}, json={"username": "alice", "password": "strong-password-123"})
        assert response.status_code == 403


def test_unchecked_remember_uses_browser_session_cookie(tmp_path):
    with client_for(tmp_path) as client:
        register(client)
        response = client.post("/api/v1/auth/login", json={"username": "alice", "password": "strong-password-123", "remember": False})
        assert response.status_code == 200
        assert "Max-Age" not in response.headers["set-cookie"]
        refreshed = client.post("/api/v1/auth/refresh")
        assert refreshed.status_code == 200
        assert "Max-Age" not in refreshed.headers["set-cookie"]
