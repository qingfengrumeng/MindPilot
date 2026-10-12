"""Durable first-turn hooks and a two-worker FIFO queue. Terminal tasks never rerun."""
from concurrent.futures import ThreadPoolExecutor
import logging
from threading import Condition, Thread
from sqlalchemy import event, select, update
from app.agents.title_domain import TitleSupervisor
from app.core.model_runtime import require_runtime_model
from app.db.models import Conversation, ConversationTitleJob, Message

log = logging.getLogger(__name__)


def install_first_turn_hook(factory):
    @event.listens_for(factory, "before_flush")
    def remember_messages(session, flush_context, instances):
        session.info["title_message_ids"] = {row.conversation_id for row in session.new
            if isinstance(row, Message) and row.role in {"user", "assistant"}}

    @event.listens_for(factory, "after_flush_postexec")
    def capture_first_turn(session, flush_context):
        ids = session.info.pop("title_message_ids", set())
        for cid in ids:
            if session.get(ConversationTitleJob, cid):
                continue
            user = session.scalar(select(Message).where(Message.conversation_id == cid, Message.role == "user")
                                  .order_by(Message.created_at, Message.id).limit(1))
            if not user:
                continue
            assistant = session.scalar(select(Message).where(Message.conversation_id == cid,
                Message.role == "assistant", Message.created_at >= user.created_at)
                .order_by(Message.created_at, Message.id).limit(1))
            if not assistant or (assistant.metadata_json or {}).get("failed"):
                continue
            conversation = session.get(Conversation, cid)
            if conversation:
                session.add(ConversationTitleJob(conversation_id=cid, status="queued",
                    expected_title=conversation.title, result_json={}, first_turn_json={
                        "user": {"id": user.id, "content": user.content},
                        "assistant": {"id": assistant.id, "content": assistant.content}}))
    return capture_first_turn


class ConversationTitleQueue:
    def __init__(self, factory, workers=2, supervisor_factory=None, model_config_path=None):
        self.factory = factory
        self.workers = max(1, min(workers, 4))
        self.make_supervisor = supervisor_factory or (lambda: TitleSupervisor(require_runtime_model("text", model_config_path)))
        self.condition = Condition()
        self.active = set()
        self.stopping = False
        self.dispatcher = None
        self.executor = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="mindpilot-title")

    def start(self):
        with self.factory() as db:
            db.execute(update(ConversationTitleJob).where(ConversationTitleJob.status == "running").values(status="queued"))
            db.commit()
        self.dispatcher = Thread(target=self._dispatch, name="mindpilot-title-dispatch", daemon=True)
        self.dispatcher.start()

    def _dispatch(self):
        while True:
            with self.condition:
                if self.stopping:
                    return
                try:
                    claimed = []
                    with self.factory() as db:
                        ids = db.scalars(select(ConversationTitleJob.conversation_id)
                            .where(ConversationTitleJob.status == "queued")
                            .order_by(ConversationTitleJob.created_at, ConversationTitleJob.conversation_id)
                            .limit(self.workers-len(self.active))).all() if len(self.active) < self.workers else []
                        for cid in ids:
                            if db.execute(update(ConversationTitleJob).where(
                                ConversationTitleJob.conversation_id == cid, ConversationTitleJob.status == "queued")
                                .values(status="running")).rowcount:
                                claimed.append(cid)
                        db.commit()
                    for cid in claimed:
                        self.active.add(cid)
                        self.executor.submit(self._run, cid)
                except Exception:
                    log.exception("First-turn title dispatch failed")
                self.condition.wait(timeout=1)

    def _run(self, cid):
        try:
            with self.factory() as db:
                job = db.get(ConversationTitleJob, cid)
                if not job:
                    return
                first_turn, expected = job.first_turn_json, job.expected_title
                conversation = db.get(Conversation, cid)
                if not conversation or conversation.title != expected:
                    job.status = "superseded"
                    db.commit()
                    return
            result = self.make_supervisor().run(first_turn)
            with self.factory() as db:
                job, conversation = db.get(ConversationTitleJob, cid), db.get(Conversation, cid)
                if not job or not conversation:
                    return
                job.result_json = result
                if conversation.title != expected:
                    job.status = "superseded"
                elif not result.get("approved"):
                    job.status = "rejected"
                else:
                    changed = db.execute(update(Conversation).where(Conversation.id == cid,
                        Conversation.title == expected, Conversation.updated_at == conversation.updated_at)
                        .values(title=result["title"], updated_at=conversation.updated_at)).rowcount
                    job.status = "completed" if changed else "superseded"
                db.commit()
        except Exception as exc:
            with self.factory() as db:
                job = db.get(ConversationTitleJob, cid)
                if job:
                    job.status = "failed"
                    job.error = type(exc).__name__
                    db.commit()
        finally:
            with self.condition:
                self.active.discard(cid)
                self.condition.notify_all()

    def shutdown(self):
        with self.condition:
            self.stopping = True
            self.condition.notify_all()
        if self.dispatcher:
            self.dispatcher.join()
        self.executor.shutdown(wait=True)
