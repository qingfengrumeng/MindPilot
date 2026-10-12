"""The imported workbench must persist content without leaking between users."""

from fastapi.testclient import TestClient
from types import SimpleNamespace

from app.core.config import Settings
from app.db.models import WorkbenchEntry, new_id
from app.main import create_app


def _client(tmp_path):
    return TestClient(create_app(Settings(
        database_url=f"sqlite:///{(tmp_path / 'workbench.db').as_posix()}",
        jwt_secret="test-secret-longer-than-thirty-two-bytes-for-jwt",
        allowed_origins=("http://localhost:5173",),
        data_dir=tmp_path,
    )))


def _login(client, name):
    client.post("/api/v1/auth/register", json={"username": name, "password": "strong-password-123"})
    token = client.post("/api/v1/auth/login", json={"username": name,
                                                  "password": "strong-password-123"}).json()["accessToken"]
    return {"Authorization": f"Bearer {token}"}


def test_database_wiki_links_owner_isolation_and_restart(tmp_path):
    with _client(tmp_path) as client:
        alice = _login(client, "alice")
        bob = _login(client, "bob")
        first = client.post("/api/v1/workbench/items", headers=alice, json={
            "kind": "wiki", "title": "RAG", "summary": "检索增强生成", "body": "来源与结论",
            "tags": ["检索"]}).json()
        second = client.post("/api/v1/workbench/items", headers=alice, json={
            "kind": "wiki", "title": "向量检索", "links": [first["id"]]}).json()
        assert first["id"] and second["id"]
        assert client.get("/api/v1/workbench/system", headers=alice).json()["entries"] == 2
        candidates = client.get("/api/v1/workbench/link-candidates", headers=alice).json()
        assert {node["id"] for node in candidates["nodes"]} == {first["id"], second["id"]}
        assert client.get(f"/api/v1/workbench/items/{second['id']}", headers=alice).json()["links"] == [first["id"]]
        assert client.get("/api/v1/workbench/link-candidates", headers=bob).json()["nodes"] == []
        from app.tools.runtime_tools import SearchQuery, _rag
        user_id = client.get("/api/v1/auth/me", headers=alice).json()["id"]
        found = _rag(SearchQuery(query="RAG 技术", top_k=5), SimpleNamespace(
            settings=client.app.state.settings, session_factory=client.app.state.session_factory,
            user_id=user_id))
        assert any(hit["documentId"] == f"wiki:{first['id']}" for hit in found["hits"])
        assert client.get("/api/v1/workbench/items?kind=wiki&q=RAG", headers=alice).json()["items"][0]["id"] == first["id"]
        assert client.get("/api/v1/workbench/items", headers=bob).json()["items"] == []
        assert client.get(f"/api/v1/workbench/items/{first['id']}", headers=bob).status_code == 404
        assert client.post("/api/v1/workbench/items", headers=bob, json={
            "kind": "wiki", "title": "越权关联", "links": [first["id"]]}).status_code == 422
        assert client.patch(f"/api/v1/workbench/items/{first['id']}", headers=alice,
                            json={"body": "更新后的正文"}).json()["body"] == "更新后的正文"
    with _client(tmp_path) as client:
        alice = _login(client, "alice")
        assert client.get(f"/api/v1/workbench/items/{first['id']}", headers=alice).json()["body"] == "更新后的正文"


def test_retired_workbench_features_are_unavailable_and_excluded_from_status(tmp_path):
    with _client(tmp_path) as client:
        headers = _login(client, "reader")
        retired_kinds = ("book", "social", "idea", "content", "douyin")
        for kind in retired_kinds:
            assert client.post("/api/v1/workbench/items", headers=headers, json={
                "kind": kind, "title": "Removed feature"}).status_code == 422
            assert client.get(f"/api/v1/workbench/items?kind={kind}", headers=headers).status_code == 422
        assert client.get("/api/v1/workbench/graph", headers=headers).status_code == 404
        assert client.post("/api/v1/workbench/douyin/import", headers=headers,
                           json={"works": []}).status_code == 404

        # An upgraded database may still contain old records. They must not
        # reappear through the generic list or system counts.
        user_id = client.get("/api/v1/auth/me", headers=headers).json()["id"]
        legacy_ids = [new_id() for _ in retired_kinds]
        with client.app.state.session_factory() as db:
            db.add_all(WorkbenchEntry(id=entry_id, user_id=user_id, kind=kind,
                                      title="Legacy record")
                       for kind, entry_id in zip(retired_kinds, legacy_ids))
            db.commit()
        created = client.post("/api/v1/workbench/items", headers=headers, json={
            "kind": "hot", "title": "知识来源", "status": "active",
            "data": {"sourceUrl": "https://example.com/source"}})
        assert created.status_code == 201, created.text
        assert client.get("/api/v1/workbench/overview", headers=headers).status_code == 404
        retained_id = created.json()["id"]
        assert [row["id"] for row in client.get("/api/v1/workbench/items", headers=headers).json()["items"]] == [retained_id]
        assert client.get("/api/v1/workbench/system", headers=headers).json()["entries"] == 1
        for entry_id in legacy_ids:
            assert client.get(f"/api/v1/workbench/items/{entry_id}", headers=headers).status_code == 404
            assert client.patch(f"/api/v1/workbench/items/{entry_id}", headers=headers,
                                json={"title": "Edit retired entry"}).status_code == 404
            assert client.post("/api/v1/workbench/items", headers=headers, json={
                "kind": "wiki", "title": "Invalid link", "links": [entry_id]}).status_code == 422
        rejected = client.post("/api/v1/workbench/items", headers=headers, json={
            "kind": "hot", "title": "不安全链接", "data": {"sourceUrl": "javascript:alert(1)"}})
        assert rejected.status_code == 422
