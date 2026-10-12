from app.core.model_preferences import write_preferences
import json
from types import SimpleNamespace

import httpx
import pytest
from app.db.session import make_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.agents.knowledge_supervisor import KnowledgeSupervisor
from app.tools.bm25_search import bm25_search
from app.tools.search_knowledge_base import hybrid_search
from app.tools.current_datetime import current_datetime_answer, is_current_datetime_question
from app.tools.web_search import BaiduSearchError, WebSearchResult, search, web_search_context
from app.agents.reflection_agent import ReflectionAgent, ReflectionResult
from app.agents.run_trace import RunTrace
from app.db.base import Base
from app.db.models import Document, DocumentChunk, Message, User
from app.core.config import Settings
from app.main import create_app
from app.api.routes.conversations import normalize_web_citations, web_citations


def test_input_and_supervisor_have_measured_duration():
    stages = RunTrace("解释 Git", False, ["Git教程.pdf"]).snapshot()["stages"]
    assert [stage["kind"] for stage in stages] == ["input", "agent"]
    assert all(stage["status"] == "ok" and stage["durationMs"] > 0 for stage in stages)
    assert stages[0]["detail"]["attachments"] == ["Git教程.pdf"]


def test_request_and_supervisor_spans_are_persisted_without_display_rounding():
    start = 1_000_000_000
    trace = RunTrace("解释 Git", False, input_span=(start, start + 5_250_000),
                     supervisor_span=(start + 5_250_000, start + 5_680_000)).snapshot()
    assert trace["stages"][0]["durationMs"] == 5.25
    assert trace["stages"][1]["durationMs"] == 0.43


def test_bm25_search_is_user_scoped_and_ignores_unready_documents(tmp_path):
    engine = make_engine(Settings(database_url=f"sqlite:///{(tmp_path / 'chunks.db').as_posix()}",
                                 jwt_secret="test-secret", allowed_origins=(), data_dir=tmp_path / "data"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as db:
        db.add_all([User(id=name, username=name, username_key=name, password_hash="test", display_name=name)
                    for name in ("alice", "bob")])
        db.flush()
        db.add_all([
            Document(id="good", user_id="alice", title="Git", filename="git.pdf", storage_path="git.pdf", status="ready"),
            Document(id="other", user_id="bob", title="Git", filename="other.pdf", storage_path="other.pdf", status="ready"),
            Document(id="pending", user_id="alice", title="Git", filename="pending.pdf", storage_path="pending.pdf", status="embedding"),
        ])
        db.add_all([
            DocumentChunk(document_id="good", chunk_index=0, page=2, text="Git 使用提交保存版本历史。", chroma_id="good:0"),
            DocumentChunk(document_id="other", chunk_index=0, page=1, text="Git 是版本控制工具。", chroma_id="other:0"),
            DocumentChunk(document_id="pending", chunk_index=0, page=1, text="Git 提交版本。", chroma_id="pending:0"),
        ])
        db.commit()
    hits = bm25_search("Git 版本", factory, "alice")
    assert [(hit["documentId"], hit["page"]) for hit in hits] == [("good", 2)]
    settings = SimpleNamespace(data_dir=tmp_path, model_config_path=tmp_path / "models.json")
    fused = hybrid_search("Git 版本", settings, factory, "alice", dense_search=lambda *args, **kwargs: [{
        "documentId": "good", "chunkIndex": 0, "page": 2, "text": "Git 使用提交保存版本历史。", "distance": 0.1,
    }])
    assert len(fused) == 1
    assert fused[0]["bm25Score"] > 0
    assert fused[0]["hybridScore"] > 1 / 61


def test_current_date_is_a_direct_clock_question_not_a_document_or_web_query():
    assert is_current_datetime_question("今天是几号")
    assert is_current_datetime_question("现在几点？")
    assert not is_current_datetime_question("今天北京天气如何")
    assert not is_current_datetime_question("今天是几号，顺便总结文档")
    assert not is_current_datetime_question("今天是几号", has_attachments=True)
    answer, detail = current_datetime_answer("今天是几号")
    assert "今天是" in answer and "星期" in answer
    assert detail["timezone"] == "Asia/Shanghai"


def test_web_search_reports_placeholder_key_instead_of_empty_result(monkeypatch):
    monkeypatch.setattr("app.tools.web_search._authorization", lambda: "CHANGE_ME")
    result = web_search_context("最新新闻")
    assert result.status == "error"
    assert "鉴权字段" in result.error
    assert not result.context


def test_web_search_uses_search_only_api_and_passes_real_pages_to_generator(monkeypatch):
    monkeypatch.setattr("app.tools.web_search._authorization", lambda: "Bearer bce-v3-test-token")
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["payload"] = kwargs["json"]
        captured["authorization"] = kwargs["headers"]["X-Appbuilder-Authorization"]
        return httpx.Response(200, json={"references": [{
            "title": "AI 产品发布", "url": "https://example.com/news", "date": "2026-09-28",
            "content": "发布了新产品。", "icon": "https://example.com/favicon.png",
        }]})

    monkeypatch.setattr("app.tools.web_search.httpx.post", fake_post)
    result = web_search_context("最新 AI 新闻")
    assert result.status == "ok"
    assert "https://example.com/news" in result.context
    assert "〔网页1〕" in result.context
    assert result.sources == [{"sourceNumber": 1, "title": "AI 产品发布",
                               "url": "https://example.com/news", "date": "2026-09-28",
                               "icon": "https://example.com/favicon.png"}]
    assert captured["url"].endswith("/v2/ai_search/web_search")
    assert captured["payload"]["search_source"] == "baidu_search_v2"
    assert "model" not in captured["payload"]
    assert captured["authorization"] == "Bearer bce-v3-test-token"


def test_web_search_rejects_bare_key_without_sending_request(monkeypatch):
    monkeypatch.setattr("app.tools.web_search._authorization", lambda: "bce-v3-test-token")
    monkeypatch.setattr("app.tools.web_search.httpx.post", lambda *_args, **_kwargs:
                        (_ for _ in ()).throw(AssertionError("The request must not be sent")))
    with pytest.raises(BaiduSearchError, match="Bearer bce-v3"):
        search("最新 AI 新闻")


def test_web_search_rejects_model_errors_even_on_http_200(monkeypatch):
    monkeypatch.setattr("app.tools.web_search._authorization", lambda: "Bearer bce-v3-test-token")
    monkeypatch.setattr("app.tools.web_search.httpx.post", lambda *_args, **_kwargs:
                        httpx.Response(200, json={"code": "invalid_model", "message": "The model does not exist"}))
    with pytest.raises(BaiduSearchError, match="模型不可用"):
        search("最新 AI 新闻")
    result = web_search_context("最新 AI 新闻")
    assert result.status == "error" and not result.context


def test_web_search_empty_pages_are_not_reported_as_success(monkeypatch):
    monkeypatch.setattr("app.tools.web_search._authorization", lambda: "Bearer bce-v3-test-token")
    monkeypatch.setattr("app.tools.web_search.httpx.post", lambda *_args, **_kwargs:
                        httpx.Response(200, json={"references": []}))
    assert web_search_context("最新 AI 新闻").status == "empty"


def test_web_citations_only_keep_verified_sources_referenced_by_answer():
    sources = [{"sourceNumber": 1, "title": "A", "url": "https://example.com/a"},
               {"sourceNumber": 2, "title": "B", "url": "https://example.com/b"}]
    assert web_citations(sources, "消息〔网页2〕和不存在的〔网页9〕") == [sources[1]]


def test_legacy_web_title_is_normalized_only_for_unique_title_and_date():
    sources = [
        {"sourceNumber": 1, "title": "新浪AI热点小时报", "url": "https://example.com/one", "date": "2026-09-23 21:00:00"},
        {"sourceNumber": 2, "title": "新浪AI热点小时报", "url": "https://example.com/two", "date": "2026-09-24 20:00:00"},
    ]
    assert normalize_web_citations("观点[新浪AI热点小时报，2026-09-23 21时]", sources) == "观点〔网页1〕"
    assert normalize_web_citations("观点[新浪AI热点小时报]", sources) == "观点[新浪AI热点小时报]"
    assert normalize_web_citations("观点[未知网页，2026-09-23]", sources) == "观点[未知网页，2026-09-23]"


def test_date_reply_skips_search_generation_reflection_and_citations(tmp_path, monkeypatch):
    env_path = tmp_path / "models.json"
    write_preferences(env_path, {'providers': {'deepseek': {'name': 'deepseek', 'runtimeProvider': 'deepseek', 'apiKey': 'test-key', 'configs': {'text': {'baseUrl': 'https://api.deepseek.com', 'model': 'deepseek-flash'}}}}, 'active': {'text': 'deepseek'}})
    for field in ("PROVIDER", "BASE_URL", "MODEL", "API_KEY"):
        monkeypatch.delenv(f"MINDPILOT_TEXT_{field}", raising=False)
    settings = Settings(database_url=f"sqlite:///{(tmp_path / 'clock.db').as_posix()}",
                        jwt_secret="test-secret-longer-than-thirty-two-bytes-for-jwt",
                        allowed_origins=("http://localhost:5173",), model_config_path=env_path, data_dir=tmp_path)

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Direct clock questions must not call retrieval, search, or an LLM")

    monkeypatch.setattr("app.api.routes.conversations.knowledge_context", unexpected)
    monkeypatch.setattr("app.api.routes.conversations.web_context", unexpected)
    monkeypatch.setattr("app.api.routes.conversations.complete_text", unexpected)
    monkeypatch.setattr("app.api.routes.conversations.stream_text", unexpected)

    app = create_app(settings)
    with TestClient(app) as client:
        client.post("/api/v1/auth/register", json={"username": "alice", "password": "strong-password-123"})
        token = client.post("/api/v1/auth/login", json={"username": "alice", "password": "strong-password-123"}).json()["accessToken"]
        headers = {"Authorization": f"Bearer {token}"}
        conversation = client.post("/api/v1/conversations", headers=headers, json={"title": "新会话"}).json()
        path = f"/api/v1/conversations/{conversation['id']}/reply"
        plain = client.post(path, headers=headers, json={"content": "今天是几号"})
        assert plain.status_code == 200, plain.text
        assert "今天是" in plain.json()["assistantMessage"]["content"]
        assert plain.json()["assistantMessage"]["metadata"]["citations"] == []

        streamed = client.post(path + "/stream", headers=headers,
                               json={"content": "今天是几号", "deepThinking": True})
        assert streamed.status_code == 200, streamed.text
        events = [json.loads(line) for line in streamed.text.splitlines()]
        done = events[-1]
        assert done["type"] == "done"
        assert done["assistantMessage"]["metadata"]["citations"] == []
        assert done["assistantMessage"]["metadata"]["workflow"]["attempts"] == 0
        assert [stage["kind"] for stage in done["trace"]["stages"]] == ["input", "agent", "tool", "output"]
        assert done["trace"]["stages"][2]["detail"]["tool"] == "current_datetime"


def test_reflection_uses_weighted_score_and_suggestions():
    def complete(_config, _messages):
        return json.dumps({"accuracy": 0.9, "completeness": 0.8, "safety": 0.7,
                           "relevance": 0.6, "suggestions": ["补充关键步骤"]}), {}

    result = ReflectionAgent(None, complete, threshold=0.8).evaluate("问题", "答案", "证据")
    assert result.score == 0.78
    assert not result.approved
    assert result.suggestions == ["补充关键步骤"]


def test_supervisor_skips_reflection_for_standard_and_caps_deep_retries():
    class Generator:
        def __init__(self):
            self.calls = []

        def stream(self, _messages):
            yield "普通回答"

        def generate(self, _messages, previous_answer="", suggestions=None):
            self.calls.append((previous_answer, suggestions))
            return f"草稿{len(self.calls)}"

    class Reviewer:
        def __init__(self):
            self.calls = 0

        def evaluate(self, *_):
            self.calls += 1
            score = 0.7 if self.calls != 2 else 0.75
            return ReflectionResult(accuracy=score, completeness=score, safety=score,
                                    relevance=score, score=score, threshold=0.8,
                                    approved=False, suggestions=["补充证据"])

    generator, reviewer = Generator(), Reviewer()
    supervisor = KnowledgeSupervisor(generator, reviewer)
    assert list(supervisor.stream_standard([])) == ["普通回答"]
    assert reviewer.calls == 0
    assert generator.calls == []
    ordinary = supervisor.complete_standard([])
    assert ordinary.answer == "草稿1"
    assert ordinary.attempts == 1
    assert ordinary.reflection is None
    assert generator.calls == [("", None)]
    assert reviewer.calls == 0
    generator.calls.clear()
    events = list(supervisor.run_deep([], "问题", "证据"))
    assert reviewer.calls == 4
    assert len(generator.calls) == 4
    assert generator.calls[1] == ("草稿1", ["补充证据"])
    assert events[-1]["outcome"].answer == "草稿2"
    assert events[-1]["outcome"].attempts == 4


def test_stream_reply_runs_reflection_only_when_deep_thinking_enabled(tmp_path, monkeypatch):
    env_path = tmp_path / "models.json"
    write_preferences(env_path, {'providers': {'deepseek': {'name': 'deepseek', 'runtimeProvider': 'deepseek', 'apiKey': 'test-key', 'configs': {'text': {'baseUrl': 'https://api.deepseek.com', 'model': 'deepseek-flash'}}}}, 'active': {'text': 'deepseek'}})
    for field in ("PROVIDER", "BASE_URL", "MODEL", "API_KEY"):
        monkeypatch.delenv(f"MINDPILOT_TEXT_{field}", raising=False)
    settings = Settings(database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
                        jwt_secret="test-secret-longer-than-thirty-two-bytes-for-jwt",
                        allowed_origins=("http://localhost:5173",), model_config_path=env_path, data_dir=tmp_path)
    calls = {"generated": 0, "reviewed": 0, "streamed": 0}

    def fake_complete(config, messages):
        if messages[0]["content"].startswith("你是严格"):
            calls["reviewed"] += 1
            grade = 0.5 if calls["reviewed"] == 1 else 0.9
            return json.dumps({"accuracy": grade, "completeness": grade, "safety": grade,
                               "relevance": grade, "suggestions": ["补充依据"] if grade < 0.8 else []}), {}
        calls["generated"] += 1
        if calls["generated"] == 2:
            assert "补充依据" in messages[1]["content"]
        return f"草稿{calls['generated']}", {"model": config.model, "tokens": {"input": 1, "output": 1}}

    def fake_stream(_config, _messages):
        calls["streamed"] += 1
        yield "普通回答"

    monkeypatch.setattr("app.api.routes.conversations.complete_text", fake_complete)
    monkeypatch.setattr("app.api.routes.conversations.stream_text", fake_stream)
    monkeypatch.setattr("app.api.routes.conversations.knowledge_context", lambda _request, _user_id, _query: (
        "Git 教程证据", [{"documentId": "document-1", "documentNumber": 1, "evidenceNumber": 1,
                          "title": "Git教程", "filename": "Git教程.pdf", "page": 2,
                          "text": "Git 保存版本历史。", "distance": 0.2}]
    ))
    app = create_app(settings)
    with TestClient(app) as client:
        client.post("/api/v1/auth/register", json={"username": "alice", "password": "strong-password-123"})
        token = client.post("/api/v1/auth/login", json={"username": "alice", "password": "strong-password-123"}).json()["accessToken"]
        headers = {"Authorization": f"Bearer {token}"}
        conversation = client.post("/api/v1/conversations", headers=headers, json={"title": "新会话"}).json()
        path = f"/api/v1/conversations/{conversation['id']}/reply/stream"
        deep = client.post(path, headers=headers, json={"content": "解释 Git", "deepThinking": True})
        assert deep.status_code == 200, deep.text
        events = [json.loads(line) for line in deep.text.splitlines()]
        deep_trace = [event["trace"] for event in events if event["type"] == "trace"][-1]
        assert deep_trace["status"] == "ok"
        assert [stage["kind"] for stage in deep_trace["stages"]].count("reflection") == 2
        assert deep_trace["stages"][0]["detail"]["question"] == "解释 Git"
        retrieval = next(stage for stage in deep_trace["stages"] if stage["kind"] == "retrieval")
        assert retrieval["detail"]["results"][0]["filename"] == "Git教程.pdf"
        assert retrieval["detail"]["results"][0]["page"] == 2
        assert retrieval["detail"]["results"][0]["text"] == "Git 保存版本历史。"
        assert [event["text"] for event in events if event["type"] == "delta"] == ["草稿2"]
        assert [event["score"] for event in events if event["type"] == "agent_review"] == [0.5, 0.9]
        assert events[-1]["assistantMessage"]["metadata"]["workflow"]["attempts"] == 2
        assert calls == {"generated": 2, "reviewed": 2, "streamed": 0}

        ordinary = client.post(path, headers=headers, json={"content": "继续", "deepThinking": False})
        assert ordinary.status_code == 200, ordinary.text
        assert calls == {"generated": 2, "reviewed": 2, "streamed": 1}
        ordinary_events = [json.loads(line) for line in ordinary.text.splitlines()]
        assert [event["text"] for event in ordinary_events if event["type"] == "delta"] == ["普通回答"]
        assert ordinary_events[-1]["assistantMessage"]["metadata"]["workflow"]["reflection"] is None
        assert ordinary_events[-1]["trace"]["status"] == "ok"
        assert all(stage["kind"] != "reflection" for stage in ordinary_events[-1]["trace"]["stages"])
        latest = client.get(f"/api/v1/conversations/{conversation['id']}/agent-runs/latest", headers=headers)
        assert latest.status_code == 200
        latest_trace = latest.json()["trace"]
        assert latest_trace["query"] == "继续"
        assert latest_trace["runId"] != deep_trace["runId"]
        assert latest_trace["status"] == "ok"
        assert [stage["kind"] for stage in latest_trace["stages"]].count("model") == 1
        assert all(stage["kind"] != "reflection" for stage in latest_trace["stages"])
        client.post("/api/v1/auth/register", json={"username": "bob", "password": "strong-password-123"})
        bob_token = client.post("/api/v1/auth/login", json={"username": "bob", "password": "strong-password-123"}).json()["accessToken"]
        assert client.get(f"/api/v1/conversations/{conversation['id']}/agent-runs/latest",
                          headers={"Authorization": f"Bearer {bob_token}"}).status_code == 404

        monkeypatch.setattr("app.api.routes.conversations.web_context",
                            lambda _query: WebSearchResult(error="百度搜索 API Key 尚未配置"))
        search_reply = client.post(path, headers=headers,
                                   json={"content": "最新 Git 新闻", "deepThinking": False})
        assert search_reply.status_code == 200, search_reply.text
        search_events = [json.loads(line) for line in search_reply.text.splitlines()]
        web_stage = next(stage for stage in search_events[-1]["trace"]["stages"]
                         if stage["detail"].get("tool") == "web_search")
        assert web_stage["status"] == "error"
        assert "API Key 尚未配置" in web_stage["summary"]
        assert search_events[-1]["assistantMessage"]["metadata"]["citations"] == []

        source = {"sourceNumber": 1, "title": "AI 产品发布", "url": "https://example.com/news",
                  "date": "2026-09-28 10:00:00", "icon": "https://example.com/favicon.png"}
        other_source = {"sourceNumber": 2, "title": "相关资料", "url": "https://example.com/related",
                        "date": "2026-09-28", "icon": ""}
        monkeypatch.setattr("app.api.routes.conversations.web_context",
                            lambda _query: WebSearchResult(context="网页证据〔网页1〕", sources=[source, other_source]))
        monkeypatch.setattr("app.api.routes.conversations.stream_text",
                            lambda _config, _messages: iter(["发布了新产品[AI 产品发布，2026-09-28 10时]"]))
        sourced_reply = client.post(path, headers=headers,
                                    json={"content": "最新 AI 新闻", "deepThinking": False})
        assert sourced_reply.status_code == 200, sourced_reply.text
        sourced_events = [json.loads(line) for line in sourced_reply.text.splitlines()]
        assert next(event for event in sourced_events if event["type"] == "tool_end" and event["tool"] == "web_search")["sources"] == [source, other_source]
        assert sourced_events[-1]["assistantMessage"]["metadata"]["webSources"] == [source, other_source]
        assert sourced_events[-1]["assistantMessage"]["content"] == "发布了新产品〔网页1〕"
        saved = client.get(f"/api/v1/conversations/{conversation['id']}/messages", headers=headers)
        assert saved.json()["items"][-1]["metadata"]["webSources"] == [source, other_source]
        assert saved.json()["items"][-1]["content"] == "发布了新产品〔网页1〕"
        # Earlier content can be upgraded in place when its saved source list is present.
        assistant_id = saved.json()["items"][-1]["id"]
        with app.state.session_factory() as session:
            message = session.get(Message, assistant_id)
            message.content = "发布了新产品[AI 产品发布，2026-09-28 10时]"
            session.commit()
        reopened = client.get(f"/api/v1/conversations/{conversation['id']}/messages", headers=headers)
        assert reopened.json()["items"][-1]["content"] == "发布了新产品〔网页1〕"
        # Older rows that lost their source metadata can be repaired from the saved run trace.
        with app.state.session_factory() as session:
            message = session.get(Message, assistant_id)
            message.metadata_json = {**message.metadata_json, "webSources": []}
            session.commit()
        reopened = client.get(f"/api/v1/conversations/{conversation['id']}/messages", headers=headers)
        assert reopened.json()["items"][-1]["metadata"]["webSources"] == [source, other_source]
        with app.state.session_factory() as session:
            assert session.get(Message, assistant_id).metadata_json["webSources"] == [source, other_source]
