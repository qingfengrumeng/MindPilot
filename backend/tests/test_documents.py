import time
from datetime import datetime, timezone

from starlette.requests import Request
from sqlalchemy import select

from app.api.routes import conversations
from app.db.models import Document, User
from app.services.document_ingestion import split_pages

from test_api import client_for, headers, login, register


def test_document_upload_then_vectorize_and_delete(tmp_path):
    with client_for(tmp_path) as client:
        register(client)
        token = login(client).json()["accessToken"]
        auth = headers(token)
        response = client.post(
            "/api/v1/documents",
            headers=auth,
            files={"file": ("notes.txt", ("第一段内容。" * 80).encode("utf-8"), "text/plain")},
            data={"domain": "reading_notes", "chunk_size": "120"},
        )
        assert response.status_code == 201, response.text
        document = response.json()
        assert document["domain"] == "reading_notes"
        imported_at = datetime.fromisoformat(document["importedAt"].replace("Z", "+00:00"))
        assert abs((datetime.now(timezone.utc) - imported_at).total_seconds()) < 10
        assert document["status"] == "uploaded"
        assert document["chunks"] == 0
        assert document["indexedChunks"] == 0
        assert client.get("/api/v1/documents", headers=auth).json()["total"] == 1
        assert client.post("/api/v1/documents/search", headers=auth, json={"query": "第一段内容", "topK": 2}).json()["items"] == []
        queued = client.post(f"/api/v1/documents/{document['id']}/vectorize", headers=auth)
        assert queued.status_code == 202, queued.text
        assert queued.json()["status"] in {"queued", "parsing", "chunking", "embedding", "ready"}
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            current = client.get(f"/api/v1/documents/{document['id']}", headers=auth).json()
            if current["status"] in {"ready", "failed"}:
                break
            time.sleep(0.05)
        assert current["status"] == "ready", current.get("errorMessage")
        assert current["chunkCount"] > 1
        assert current["indexedChunks"] == current["chunkCount"]
        assert client.post(f"/api/v1/documents/{document['id']}/vectorize", headers=auth).status_code == 409
        search = client.post("/api/v1/documents/search", headers=auth, json={"query": "第一段内容", "topK": 2})
        assert search.status_code == 200
        assert search.json()["items"]
        detail = client.get(f"/api/v1/documents/{document['id']}", headers=auth)
        assert detail.status_code == 200
        assert detail.json()["chunkCount"] == current["chunkCount"]
        assert client.delete(f"/api/v1/documents/{document['id']}", headers=auth).status_code == 204
        assert client.get("/api/v1/documents", headers=auth).json()["total"] == 0


def test_split_pages_keeps_page_metadata():
    chunks = split_pages([(3, "abcdef " * 100)], chunk_size=100)
    assert chunks
    assert all(item["page"] == 3 for item in chunks)


def test_knowledge_citations_number_documents_and_verify_pdf_pages(tmp_path, monkeypatch):
    with client_for(tmp_path) as client:
        register(client)
        with client.app.state.session_factory() as db:
            user = db.scalar(select(User).where(User.username_key == "alice"))
            user_id = user.id
            db.add_all([
                Document(id="pdf-doc", user_id=user_id, title="Git 教程", filename="git.pdf", storage_path="git.pdf", pages=3, status="ready"),
                Document(id="text-doc", user_id=user_id, title="阅读笔记", filename="notes.txt", storage_path="notes.txt", pages=1, status="ready"),
            ])
            db.commit()
        hits = [
            {"documentId": "pdf-doc", "page": 1, "text": "第一页", "distance": 0.1},
            {"documentId": "pdf-doc", "page": 3, "text": "第三页", "distance": 0.2},
            {"documentId": "text-doc", "page": 1, "text": "文本内容", "distance": 0.3},
            {"documentId": "pdf-doc", "page": 9, "text": "错误页码", "distance": 0.4},
        ]
        monkeypatch.setattr(conversations, "search_documents", lambda *args, **kwargs: hits)
        context, verified = conversations.knowledge_context(Request({"type": "http", "app": client.app}), user_id, "Git 是什么")
        assert [item["documentNumber"] for item in verified] == [1, 1, 2]
        assert [item["page"] for item in verified] == [1, 3, None]
        assert [item["filename"] for item in verified] == ["git.pdf", "git.pdf", "notes.txt"]
        assert "〔证据2〕 文档1《Git 教程》第3页" in context
        assert "〔证据3〕 文档2《阅读笔记》无页码" in context
        assert "错误页码" not in context
