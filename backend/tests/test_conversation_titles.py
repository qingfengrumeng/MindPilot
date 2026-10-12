import json
import time
from threading import Event, Lock
from sqlalchemy import select, func
from app.agents.title_domain import TitleSupervisor
from app.db.models import Conversation, ConversationTitleJob, Message
from tests.test_api import client_for, headers, login, register


def wait_for(predicate, timeout=6):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(.02)
    raise AssertionError("title task timed out")


def auth(client):
    register(client)
    return headers(login(client).json()["accessToken"])


def create(client, access):
    return client.post("/api/v1/conversations", headers=access, json={}).json()["id"]


def message(client, access, cid, role, content):
    response = client.post(f"/api/v1/conversations/{cid}/messages", headers=access,
                          json={"role": role, "content": content})
    assert response.status_code == 201, response.text
    return response.json()


def status(client, access, cid):
    return client.get(f"/api/v1/conversations/{cid}/title-generation", headers=access).json()


def test_first_reply_triggers_once_and_freezes_first_pair(tmp_path):
    with client_for(tmp_path) as client:
        access = auth(client)
        started, release = Event(), Event()
        calls = []
        class Supervisor:
            def run(self, pair):
                calls.append(pair)
                started.set()
                release.wait(5)
                return {"approved": True, "title": "AI活动海报设计"}
        client.app.state.title_queue.make_supervisor = Supervisor
        cid = create(client, access)
        assert status(client, access, cid)["status"] == "idle"
        first = message(client, access, cid, "user", "首轮海报需求")
        assert status(client, access, cid)["status"] == "idle"
        answer = message(client, access, cid, "assistant", "首轮已生成海报")
        assert started.wait(3)
        message(client, access, cid, "user", "后续修改二维码")
        message(client, access, cid, "assistant", "已修改二维码")
        with client.app.state.session_factory() as db:
            before = db.get(Conversation, cid).updated_at
        release.set()
        wait_for(lambda: status(client, access, cid)["status"] == "completed")
        assert status(client, access, cid)["title"] == "AI活动海报设计"
        assert calls == [{"user": {"id": first["id"], "content": "首轮海报需求"},
                          "assistant": {"id": answer["id"], "content": "首轮已生成海报"}}]
        message(client, access, cid, "user", "第三轮内容")
        message(client, access, cid, "assistant", "第三轮答案")
        assert len(calls) == 1
        with client.app.state.session_factory() as db:
            assert db.scalar(select(func.count()).select_from(ConversationTitleJob)) == 1
        # No public endpoint can trigger another workflow.
        assert client.post(f"/api/v1/conversations/{cid}/title-generation", headers=access).status_code == 405
        register(client, username="bob")
        bob = headers(login(client, username="bob").json()["accessToken"])
        assert client.get(f"/api/v1/conversations/{cid}/title-generation", headers=bob).status_code == 404


def test_atomic_pair_commit_and_rollback(tmp_path):
    with client_for(tmp_path) as client:
        access = auth(client)
        cid = create(client, access)
        with client.app.state.session_factory() as db:
            db.add_all([Message(conversation_id=cid, role="user", content="输入"),
                        Message(conversation_id=cid, role="assistant", content="输出")])
            db.flush()
            assert db.get(ConversationTitleJob, cid) is not None
            db.rollback()
        with client.app.state.session_factory() as db:
            assert db.get(ConversationTitleJob, cid) is None
        message(client, access, cid, "user", "重新输入")
        message(client, access, cid, "assistant", "重新输出")
        wait_for(lambda: status(client, access, cid)["status"] == "rejected")


def test_failure_and_rejection_never_retrigger_on_later_messages_or_restart(tmp_path):
    calls = []
    with client_for(tmp_path) as client:
        access = auth(client)
        class Broken:
            def run(self, pair):
                calls.append(pair)
                raise RuntimeError("offline")
        client.app.state.title_queue.make_supervisor = Broken
        cid = create(client, access)
        message(client, access, cid, "user", "首问")
        message(client, access, cid, "assistant", "首答")
        wait_for(lambda: status(client, access, cid)["status"] == "failed")
        message(client, access, cid, "user", "后问")
        message(client, access, cid, "assistant", "后答")
        assert len(calls) == 1
    next_client = client_for(tmp_path)
    class Unexpected:
        def run(self, pair):
            calls.append(pair)
            return {"approved": True, "title": "不应执行"}
    next_client.app.state.title_queue.make_supervisor = Unexpected
    with next_client as client:
        access = headers(login(client).json()["accessToken"])
        message(client, access, cid, "user", "重启后提问")
        message(client, access, cid, "assistant", "重启后答案")
        assert status(client, access, cid)["status"] == "failed" and len(calls) == 1


def test_two_workers_and_fifo_waiting(tmp_path):
    with client_for(tmp_path) as client:
        access = auth(client)
        lock = Lock()
        started, release = Event(), Event()
        calls, running, peak = [], 0, 0
        class Supervisor:
            def run(self, pair):
                nonlocal running, peak
                with lock:
                    calls.append(pair)
                    running += 1
                    peak = max(peak, running)
                    if running == 2:
                        started.set()
                release.wait(5)
                with lock:
                    running -= 1
                return {"approved": True, "title": "海报设计"}
        client.app.state.title_queue.make_supervisor = Supervisor
        ids = []
        for _ in range(4):
            # Populate each draft before requesting the next default conversation.
            cid = create(client, access)
            ids.append(cid)
            message(client, access, cid, "user", "首问")
            message(client, access, cid, "assistant", "首答")
        assert started.wait(3)
        with client.app.state.session_factory() as db:
            jobs = db.scalars(select(ConversationTitleJob)).all()
            assert sum(job.status == "running" for job in jobs) == 2
            assert sum(job.status == "queued" for job in jobs) == 2
        release.set()
        wait_for(lambda: all(status(client, access, cid)["status"] == "completed" for cid in ids))
        assert len(calls) == 4 and peak == 2


def test_manual_rename_is_preserved_and_title_update_does_not_change_activity(tmp_path):
    with client_for(tmp_path) as client:
        access = auth(client)
        started, release = Event(), Event()
        class Supervisor:
            def run(self, pair):
                started.set()
                release.wait(5)
                return {"approved": True, "title": "生成标题"}
        client.app.state.title_queue.make_supervisor = Supervisor
        cid = create(client, access)
        message(client, access, cid, "user", "首问")
        message(client, access, cid, "assistant", "首答")
        assert started.wait(3)
        client.patch(f"/api/v1/conversations/{cid}", headers=access, json={"title": "手动名称"})
        release.set()
        wait_for(lambda: status(client, access, cid)["status"] == "superseded")
        assert status(client, access, cid)["title"] == "手动名称"
        # A separate conversation exercises the successful optimistic write.
        client.app.state.title_queue.make_supervisor = Supervisor
        other = create(client, access)
        message(client, access, other, "user", "首问")
        message(client, access, other, "assistant", "首答")
        with client.app.state.session_factory() as db:
            before = db.get(Conversation, other).updated_at
        wait_for(lambda: status(client, access, other)["status"] == "completed")
        with client.app.state.session_factory() as db:
            assert db.get(Conversation, other).updated_at == before


def test_supervisor_feedback_and_short_title_review():
    prompts = []
    responses = iter([{"title": "天气查询"}, {"accuracy": .2, "completeness": .2, "relevance": .2, "concision": 1,
        "suggestions": ["核心任务为活动海报设计"]}, {"title": "AI活动海报设计"},
        {"accuracy": 1, "completeness": 1, "relevance": 1, "concision": 1}])
    def model(config, messages):
        prompts.append(messages)
        return json.dumps(next(responses), ensure_ascii=False), {}
    result = TitleSupervisor(None, model).run({"user": {"content": "活动海报"}, "assistant": {"content": "已生成"}})
    assert result["approved"] and result["title"] == "AI活动海报设计"
    assert len(result["attempts"]) == 2
    assert "核心任务为活动海报设计" in prompts[2][1]["content"]


def test_three_drafts_and_ten_character_limit():
    calls = []
    def model(config, messages):
        calls.append(messages)
        value = {"title": "一二三四五六七八九十一"} if len(calls) % 2 else {
            "accuracy": 1, "completeness": 1, "relevance": 1, "concision": 1}
        return json.dumps(value, ensure_ascii=False), {}
    result = TitleSupervisor(None, model).run({"user": {"content": "首問"}, "assistant": {"content": "首答"}})
    assert not result["approved"] and len(calls) == 6 and len(result["attempts"]) == 3
