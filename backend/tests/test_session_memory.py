import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.security import utcnow
from app.db.base import Base
from app.db.models import (AgentRun, AgentTask, Conversation, ConversationJournal, MemoryDocument,
                           MemoryExtraction, Message, SessionEvent, User)
from app.db.session import make_engine
from app.services.conversation_context import ConversationContext, TokenCounter
from app.services.long_term_memory import LongTermMemory
from app.services.session_journal import SessionJournal
from app.services.state_files import MemoryPolicy


@pytest.fixture
def storage(tmp_path):
    settings = Settings(database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        jwt_secret="test-secret-longer-than-thirty-two-bytes", allowed_origins=(),
        model_config_path=tmp_path / ".mindpoilt" / "models.json", state_dir=tmp_path / ".mindpoilt",
        data_dir=tmp_path / "data")
    engine = make_engine(settings)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    journal = SessionJournal(settings, factory)
    journal.install()
    with factory() as db:
        user = User(username="alice", username_key="alice", display_name="Alice", password_hash="not-used")
        db.add(user)
        db.commit()
        conversation = Conversation(user_id=user.id, title="项目讨论")
        db.add(conversation)
        db.commit()
    yield SimpleNamespace(settings=settings, engine=engine, factory=factory,
                          journal=journal, user=user, conversation=conversation)
    engine.dispose()


def add_turns(storage, start, count, *, verbose=True, age_hours=0, content_multiplier=1):
    rows = []
    with storage.factory() as db:
        for number in range(start, start + count):
            created = utcnow() - timedelta(hours=age_hours) + timedelta(microseconds=number * 2)
            user = Message(conversation_id=storage.conversation.id, role="user",
                content=f"问题{number}:" + ("资料" * 80 * content_multiplier if verbose else "请保持简洁"), created_at=created)
            assistant = Message(conversation_id=storage.conversation.id, role="assistant",
                content=f"回答{number}", created_at=created + timedelta(microseconds=1))
            db.add_all((user, assistant))
            rows.extend((user, assistant))
        db.commit()
    return rows


def configure(storage, **changes):
    policy = MemoryPolicy(**changes)
    storage.journal.files.atomic_write(storage.journal.files.path("config.toml"), storage.journal.files.policy_toml(policy))
    return policy


def model_context(storage, **kwargs):
    context = ConversationContext(storage.journal)
    return context.build(storage.user.id, storage.conversation.id, object(),
        [{"role": "system", "content": "你是助手"}], {"role": "user", "content": "继续"},
        lambda text, attachments: text, **kwargs)


def test_full_history_then_compaction_retains_ten_complete_turns_without_gaps(storage):
    original = add_turns(storage, 0, 15)
    full = model_context(storage, completion=lambda *args: pytest.fail("threshold not reached"))
    assert len(full) == 32
    assert full[1]["content"] == original[0].content
    configure(storage, context_window_tokens=16000, auto_compact_token_limit=2000,
              response_reserve_tokens=2000, summary_max_tokens=128)
    requests = []
    def compress(config, messages):
        requests.append(messages)
        return "累积摘要" + str(len(requests)), {}
    compressed = model_context(storage, completion=compress)
    assert len(compressed) == 23
    assert compressed[2:22] == [{"role": row.role, "content": row.content} for row in original[-20:]]
    assert original[0].content[:10] in "".join(row[1]["content"] for row in requests)
    events = storage.journal.events(storage.user.id, storage.conversation.id)
    first = [row for row in events if row["type"] == "compacted"][-1]
    assert first["payload"]["covered_message_ids"] == [row.id for row in original[:10]]
    assert len(storage.journal.messages(storage.user.id, storage.conversation.id)) == 30
    previous_calls = len(requests)
    assert model_context(storage, completion=compress) == compressed
    assert len(requests) == previous_calls
    added = add_turns(storage, 15, 1)
    second = model_context(storage, completion=compress)
    assert second[-3:-1] == [{"role": row.role, "content": row.content} for row in added]
    assert original[10].content[:10] in requests[-1][1]["content"]
    assert first["payload"]["summary"] in requests[-1][1]["content"]
    compacted = [row for row in storage.journal.events(storage.user.id, storage.conversation.id) if row["type"] == "compacted"]
    assert len(compacted) == 2
    assert compacted[1]["payload"]["previous_window_id"] == compacted[0]["payload"]["window_id"]
    assert compacted[1]["payload"]["covered_message_ids"] == [row.id for row in original[:12]]
    assert len(storage.journal.messages(storage.user.id, storage.conversation.id)) == 32


def test_edits_deletes_and_regeneration_invalidate_old_summary(storage):
    original = add_turns(storage, 0, 15)
    configure(storage, context_window_tokens=16000, auto_compact_token_limit=2000,
              response_reserve_tokens=2000, summary_max_tokens=128)
    requests = []
    def compress(config, messages):
        requests.append(messages)
        return "摘要", {}
    model_context(storage, completion=compress)
    with storage.factory() as db:
        db.get(Message, original[1].id).content = "已经修正的回答"
        db.commit()
    model_context(storage, completion=compress)
    assert "已经修正的回答" in "".join(request[1]["content"] for request in requests[1:])
    latest = [row for row in storage.journal.events(storage.user.id, storage.conversation.id) if row["type"] == "compacted"][-1]
    assert latest["payload"]["previous_window_id"] is None
    earlier = model_context(storage, before_message_id=original[10].id,
                            completion=lambda *args: pytest.fail("small regeneration view"))
    assert len([row for row in earlier if row["role"] == "user"]) == 6
    assert original[10].content not in str(earlier)
    with storage.factory() as db:
        db.delete(db.get(Message, original[0].id))
        db.commit()
    assert original[0].id not in [row.id for row in storage.journal.messages(storage.user.id, storage.conversation.id)]
    assert any(row["type"] == "message_deleted" for row in storage.journal.events(storage.user.id, storage.conversation.id))


def test_tools_roundtrip_without_truncating_recent_turns(storage):
    rows = add_turns(storage, 0, 1, verbose=False)
    with storage.factory() as db:
        run = AgentRun(conversation_id=storage.conversation.id, trace_json={"status": "ok", "stages": [{
            "id": "tool-stage", "kind": "tool", "status": "ok", "title": "检索",
            "detail": {"tool": "search", "query": "问题", "result": "完整结果" * 500,
                       "api_key": "do-not-log"}}]})
        db.add(run)
        db.flush()
        db.get(Message, rows[1].id).metadata_json = {"agentRunId": run.id}
        db.commit()
    result = model_context(storage)
    assert "完整结果" * 500 in result[-2]["content"]
    events = storage.journal.events(storage.user.id, storage.conversation.id)
    assert {"tool_call", "tool_result"} <= {row["type"] for row in events}
    assert "do-not-log" not in storage.journal.path(storage.user.id, storage.conversation.id).read_text(encoding="utf-8")


def test_outbox_replays_after_partial_delivery_and_rollback_does_not_log(storage, monkeypatch):
    append = storage.journal.append
    def append_then_fail(*args, **kwargs):
        append(*args, **kwargs)
        raise OSError("simulated crash after durable append")
    monkeypatch.setattr(storage.journal, "append", append_then_fail)
    rows = add_turns(storage, 0, 1, verbose=False)
    with storage.factory() as db:
        assert db.scalar(select(SessionEvent).where(SessionEvent.delivered.is_(False)))
    monkeypatch.setattr(storage.journal, "append", append)
    storage.journal.drain()
    assert [row.id for row in storage.journal.messages(storage.user.id, storage.conversation.id)] == [row.id for row in rows]
    records = storage.journal.events(storage.user.id, storage.conversation.id)
    assert len({row["event_id"] for row in records}) == len(records)
    with storage.factory() as db:
        db.add(Message(conversation_id=storage.conversation.id, role="user", content="必须回滚"))
        db.flush()
        db.rollback()
    assert "必须回滚" not in storage.journal.path(storage.user.id, storage.conversation.id).read_text(encoding="utf-8")


def test_torn_append_recovery_backfill_and_account_isolation(storage):
    rows = add_turns(storage, 0, 2, verbose=False)
    path = storage.journal.path(storage.user.id, storage.conversation.id)
    with path.open("ab") as handle:
        handle.write(b'{"incomplete":')
    storage.journal.append(storage.user.id, storage.conversation.id, "test", {})
    assert len(storage.journal.messages(storage.user.id, storage.conversation.id)) == 4
    assert storage.journal.messages("another-user", storage.conversation.id) == []
    with pytest.raises(ValueError):
        storage.journal.path("../outside", storage.conversation.id)
    with storage.factory() as db:
        db.info["journal_suppressed"] = True
        legacy = Conversation(user_id=storage.user.id, title="迁移前的历史")
        db.add(legacy)
        db.flush()
        db.add(Message(conversation_id=legacy.id, role="user", content="旧内容"))
        db.commit()
    storage.journal.backfill()
    storage.journal.backfill()
    imported = storage.journal.messages(storage.user.id, legacy.id)
    assert len(imported) == 1 and imported[0].content == "旧内容"
    with storage.factory() as db:
        db.delete(db.get(Conversation, legacy.id))
        db.commit()
    assert not storage.journal.path(storage.user.id, legacy.id).exists()


def test_dated_layout_migration_preserves_events_and_recovers_interrupted_index_commit(storage, monkeypatch):
    add_turns(storage, 0, 2, verbose=False)
    storage.journal.append(storage.user.id, storage.conversation.id, "compacted", {"summary": "旧摘要"})
    dated = storage.journal.path(storage.user.id, storage.conversation.id)
    original = dated.read_bytes()
    legacy = storage.journal.files.path("sessions", storage.user.id, storage.conversation.id + ".jsonl")
    legacy.parent.mkdir(parents=True)
    dated.replace(legacy)
    with storage.factory() as db:
        db.info["journal_suppressed"] = True
        db.get(ConversationJournal, storage.conversation.id).relative_path = legacy.relative_to(storage.journal.files.root).as_posix()
        db.commit()
    resumed = SessionJournal(storage.settings, storage.factory)
    session_class = storage.factory.class_
    def fail_before_checkpoint(db):
        raise OSError("crash after rollout move, before SQLite commit")
    with monkeypatch.context() as patch:
        patch.setattr(session_class, "commit", fail_before_checkpoint)
        with pytest.raises(OSError):
            resumed.migrate_layout()
    assert dated.read_bytes() == original and not legacy.exists()
    restarted = SessionJournal(storage.settings, storage.factory)
    restarted.migrate_layout()
    restarted.migrate_layout()
    assert restarted.path(storage.user.id, storage.conversation.id) == dated
    assert dated.read_bytes() == original
    date = storage.conversation.created_at
    assert dated.relative_to(storage.journal.files.root).parts[:4] == ("sessions", date.strftime("%Y"), date.strftime("%m"), date.strftime("%d"))
    assert dated.name == f"rollout-{date.strftime('%Y-%m-%dT%H-%M-%S')}-{storage.conversation.id}.jsonl"
    assert not legacy.parent.exists()
    index = json.loads((storage.journal.files.root / "session_index.jsonl").read_text(encoding="utf-8"))
    assert index["rollout_path"] == dated.relative_to(storage.journal.files.root).as_posix()
    assert restarted.messages("another-user", storage.conversation.id) == []


def test_pending_whole_session_delete_is_recovered_after_restart_without_orphan_rollout(storage, monkeypatch):
    add_turns(storage, 0, 2, verbose=False)
    path = storage.journal.path(storage.user.id, storage.conversation.id)
    def fail_delete(*args, **kwargs):
        raise OSError("unavailable filesystem")
    monkeypatch.setattr(storage.journal, "delete", fail_delete)
    with storage.factory() as db:
        db.delete(db.get(Conversation, storage.conversation.id))
        db.commit()
    assert path.exists()
    restarted = SessionJournal(storage.settings, storage.factory)
    restarted.drain()
    assert not path.exists()
    assert not list(restarted.files.path("sessions").rglob("*.jsonl"))
    assert (restarted.files.root / "session_index.jsonl").read_text(encoding="utf-8") == ""


def test_json_policy_upgrades_to_validated_toml_and_keeps_rollback_copy(storage):
    policy = MemoryPolicy(memory_min_idle_hours=12, auto_compact_token_limit=18000)
    legacy = storage.journal.files.path("config.json")
    original = policy.model_dump_json(indent=2)
    legacy.write_text(original, encoding="utf-8")
    assert storage.journal.files.policy() == policy
    assert not legacy.exists()
    assert storage.journal.files.path("backups", "legacy-config.json").read_text(encoding="utf-8") == original
    assert "[memory]" in storage.journal.files.path("config.toml").read_text(encoding="utf-8")
    storage.journal.files.atomic_write(storage.journal.files.path("config.toml"), 'format_version = 1\n[memory]\nrecent_turns = 9\n')
    with pytest.raises(RuntimeError, match="config.toml"):
        storage.journal.files.policy()


def test_context_overflow_keeps_original_history_and_never_silently_drops_ten_turns(storage):
    # Exceed the window both with cl100k_base and the conservative byte fallback.
    original = add_turns(storage, 0, 15, content_multiplier=4)
    configure(storage, context_window_tokens=2048, auto_compact_token_limit=1200,
              response_reserve_tokens=128, summary_max_tokens=128)
    with pytest.raises(HTTPException) as error:
        model_context(storage, completion=lambda *args: ("摘要", {}))
    assert error.value.status_code == 413
    assert len(storage.journal.messages(storage.user.id, storage.conversation.id)) == len(original)
    assert not any(row["type"] == "compacted" for row in storage.journal.events(storage.user.id, storage.conversation.id))


def test_long_term_idle_extraction_consolidation_files_and_selective_retrieval(storage, monkeypatch):
    rows = add_turns(storage, 0, 2, verbose=False, age_hours=7)
    worker = LongTermMemory(storage.journal, storage.settings, storage.factory)
    calls = []
    def complete(config, messages):
        calls.append(messages)
        if "rollout_summary" in messages[0]["content"]:
            return json.dumps({"rollout_summary": "项目讨论", "entries": [{"kind": "preference",
                "text": "用户要求回答简洁", "evidence_message_ids": [rows[0].id]}]}, ensure_ascii=False), {}
        candidates = json.loads(messages[1]["content"])
        return json.dumps({"entries": candidates}, ensure_ascii=False), {}
    monkeypatch.setattr("app.services.long_term_memory.require_runtime_model", lambda *args: object())
    monkeypatch.setattr("app.services.long_term_memory.complete_text", complete)
    assert worker.run_pass() == 1
    assert len(calls) == 2
    root = worker.directory(storage.user.id)
    assert (root / "memory_summary.md").is_file()
    assert (root / "MEMORY.md").is_file()
    assert (root / "rollout_summaries" / (storage.conversation.id + ".md")).is_file()
    assert "用户要求回答简洁" in worker.retrieve(storage.user.id, "继续这个项目", worker.files.policy(), TokenCounter())
    assert worker.retrieve("another-user", "项目", worker.files.policy(), TokenCounter()) == ""
    assert worker.run_pass() == 0
    assert len(calls) == 2
    with storage.factory() as db:
        assert db.get(MemoryExtraction, storage.conversation.id).status == "complete"
        db.delete(db.get(Conversation, storage.conversation.id))
        db.commit()
    assert "用户要求回答简洁" not in worker.retrieve(storage.user.id, "项目", worker.files.policy(), TokenCounter())
    worker.run_pass()
    assert "用户要求回答简洁" not in (root / "MEMORY.md").read_text(encoding="utf-8")


def test_memory_skips_active_recent_chats_and_rejects_invented_preference_evidence(storage, monkeypatch):
    rows = add_turns(storage, 0, 2, verbose=False)
    worker = LongTermMemory(storage.journal, storage.settings, storage.factory)
    assert worker.run_pass() == 0
    monkeypatch.setattr("app.services.long_term_memory.require_runtime_model", lambda *args: object())
    monkeypatch.setattr("app.services.long_term_memory.complete_text", lambda *args: (json.dumps({
        "rollout_summary": "", "entries": [{"kind": "preference", "text": "虚构偏好",
                                             "evidence_message_ids": [rows[1].id]}]}), {}))
    worker.run_pass(storage.user.id, force=True)
    with storage.factory() as db:
        job = db.get(MemoryExtraction, storage.conversation.id)
        assert job.status == "failed" and job.retry_at
    assert "虚构偏好" not in (worker.directory(storage.user.id) / "MEMORY.md").read_text(encoding="utf-8")


def test_memory_evidence_edits_are_filtered_from_summary_and_handbook(storage, monkeypatch):
    rows = add_turns(storage, 0, 2, verbose=False, age_hours=7)
    worker = LongTermMemory(storage.journal, storage.settings, storage.factory)
    def complete(config, messages):
        if "rollout_summary" in messages[0]["content"]:
            return json.dumps({"rollout_summary": "已讨论偏好", "entries": [{"kind": "preference", "text": "用户要求回答简洁",
                "evidence_message_ids": [rows[0].id]}]}, ensure_ascii=False), {}
        return json.dumps({"entries": json.loads(messages[1]["content"])}, ensure_ascii=False), {}
    monkeypatch.setattr("app.services.long_term_memory.require_runtime_model", lambda *args: object())
    monkeypatch.setattr("app.services.long_term_memory.complete_text", complete)
    worker.run_pass()
    assert "用户要求回答简洁" in worker.retrieve(storage.user.id, "偏好", worker.files.policy(), TokenCounter())
    with storage.factory() as db:
        db.get(Message, rows[0].id).content = "现在希望详细说明"
        db.commit()
    assert "用户要求回答简洁" not in worker.retrieve(storage.user.id, "偏好", worker.files.policy(), TokenCounter())


def test_background_generation_lock_does_not_block_other_session_files(storage):
    from concurrent.futures import ThreadPoolExecutor
    with storage.journal.files.lock("memory-generation"):
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(storage.journal.events, storage.user.id, storage.conversation.id)
            assert future.result(timeout=3)


def test_api_sync_and_stream_use_same_compaction_policy_and_hide_internal_events(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.core.model_preferences import write_preferences
    settings = Settings(database_url=f"sqlite:///{(tmp_path / 'api.db').as_posix()}",
        jwt_secret="test-secret-longer-than-thirty-two-bytes", allowed_origins=(),
        model_config_path=tmp_path / ".mindpoilt" / "models.json", state_dir=tmp_path / ".mindpoilt",
        data_dir=tmp_path / "data")
    write_preferences(settings.model_config_path, {"providers": {"deepseek": {"name": "DeepSeek",
        "runtimeProvider": "deepseek", "apiKey": "private-test-key", "configs": {"text": {
        "baseUrl": "https://api.deepseek.com", "model": "deepseek-flash"}}}}, "active": {"text": "deepseek"}})
    seen = []
    def complete(config, messages):
        if "压缩会话上下文" in messages[0]["content"]:
            return "历史摘要", {}
        seen.append(messages)
        return "普通回答", {}
    def stream(config, messages):
        seen.append(messages)
        yield "流式回答"
    monkeypatch.setattr("app.api.routes.conversations.complete_text", complete)
    monkeypatch.setattr("app.api.routes.conversations.stream_text", stream)
    with TestClient(create_app(settings)) as client:
        client.post("/api/v1/auth/register", json={"username": "alice", "password": "strong-password-123"})
        token = client.post("/api/v1/auth/login", json={"username": "alice", "password": "strong-password-123"}).json()["accessToken"]
        headers = {"Authorization": f"Bearer {token}"}
        conversation = client.post("/api/v1/conversations", headers=headers, json={"title": "上下文测试"}).json()
        with client.app.state.session_factory() as db:
            user = db.scalar(select(User).where(User.username_key == "alice"))
        storage = SimpleNamespace(settings=settings, factory=client.app.state.session_factory,
            journal=client.app.state.session_journal, user=user, conversation=SimpleNamespace(id=conversation["id"]))
        configure(storage, context_window_tokens=16000, auto_compact_token_limit=2000,
                  response_reserve_tokens=2000, summary_max_tokens=128)
        add_turns(storage, 0, 15)
        base = f"/api/v1/conversations/{conversation['id']}"
        response = client.post(base + "/reply", headers=headers, json={"content": "同步问题"})
        assert response.status_code == 200, response.text
        assert "历史摘要" in str(seen[0])
        assert len([row for row in seen[0] if row["role"] == "user"]) == 11
        response = client.post(base + "/reply/stream", headers=headers, json={"content": "流式问题"})
        assert response.status_code == 200, response.text
        assert json.loads(response.text.splitlines()[-1])["type"] == "done"
        assert len([row for row in seen[1] if row["role"] == "user"]) == 11
        messages = client.get(base + "/messages", headers=headers).json()["items"]
        assert len(messages) == 34
        assert not any(row["content"] == "历史摘要" for row in messages)
        assert client.get("/api/v1/memories").status_code == 401
        status = client.get("/api/v1/memories", headers=headers).json()
        assert status["recentTurns"] == 10 and status["entries"] == 0
        assert "private-test-key" not in str(status)


def test_long_term_redacts_configured_credentials_before_model_and_disk(storage, monkeypatch):
    from app.core.model_preferences import write_preferences
    key = "private-model-credential"
    write_preferences(storage.settings.model_config_path, {"providers": {"deepseek": {"name": "DeepSeek",
        "runtimeProvider": "deepseek", "apiKey": key, "configs": {"text": {
        "baseUrl": "https://api.deepseek.com", "model": "deepseek-flash"}}}}, "active": {"text": "deepseek"}})
    rows = add_turns(storage, 0, 2, verbose=False, age_hours=7)
    with storage.factory() as db:
        db.get(Message, rows[0].id).content += " API Key: " + key
        db.commit()
    worker = LongTermMemory(storage.journal, storage.settings, storage.factory)
    def complete(config, messages):
        assert key not in str(messages)
        return json.dumps({"rollout_summary": "API Key: " + key, "entries": [{"kind": "preference",
            "text": "保存 API Key: " + key, "evidence_message_ids": [rows[0].id]}]}, ensure_ascii=False), {}
    monkeypatch.setattr("app.services.long_term_memory.require_runtime_model", lambda *args: object())
    monkeypatch.setattr("app.services.long_term_memory.complete_text", complete)
    worker.run_pass()
    for path in worker.directory(storage.user.id).rglob("*.md"):
        assert key not in path.read_text(encoding="utf-8")
    with storage.factory() as db:
        assert key not in str(db.get(MemoryExtraction, storage.conversation.id).result_json)


def test_running_agent_task_blocks_memory_extraction_even_for_idle_history(storage):
    add_turns(storage, 0, 2, verbose=False, age_hours=7)
    with storage.factory() as db:
        db.add(AgentTask(user_id=storage.user.id, conversation_id=storage.conversation.id,
            agent_id="drawing", goal="正在生成", status="running", inputs_json={}, constraints_json={}, result_json={}))
        db.commit()
    worker = LongTermMemory(storage.journal, storage.settings, storage.factory)
    assert worker.run_pass(storage.user.id, force=True) == 0
    with storage.factory() as db:
        assert db.get(MemoryExtraction, storage.conversation.id) is None


def test_new_orm_conversation_graph_journals_messages_after_ids_are_assigned(storage):
    with storage.factory() as db:
        conversation = Conversation(user_id=storage.user.id, title="同一事务创建",
            messages=[Message(role="user", content="第一个问题"), Message(role="assistant", content="第一个回答")])
        db.add(conversation)
        db.commit()
    assert [row.content for row in storage.journal.messages(storage.user.id, conversation.id)] == ["第一个问题", "第一个回答"]
