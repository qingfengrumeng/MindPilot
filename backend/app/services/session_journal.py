"""Append-only session events, with SQLite projections and a transactional outbox."""
from collections import OrderedDict
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import PurePosixPath
from types import SimpleNamespace

from sqlalchemy import event, select, update

from app.core.security import utcnow
from app.db.models import (AgentRun, AgentTask, AgentTaskEvent, Conversation,
                           ConversationInheritance, ConversationJournal, Message, SessionEvent, new_id)
from app.services.state_files import StateFiles, safe_id

log = logging.getLogger(__name__)


def stamp(value):
    value = value or utcnow()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def protected_data(value):
    """Tool credentials are never serialized into logs."""
    if isinstance(value, dict):
        return {str(key): "[REDACTED_SECRET]" if any(s in str(key).lower().replace("_", "")
                for s in ("apikey", "password", "authorization", "secret", "accesstoken", "refreshtoken"))
                else protected_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [protected_data(item) for item in value]
    return value


class SessionJournal:
    def __init__(self, settings, factory):
        self.files = StateFiles(settings)
        self.factory = factory
        self._paths = {}

    def rollout_path(self, relative):
        parts = PurePosixPath(relative).parts
        if not parts or parts[0] not in {"sessions", "archived_sessions"} or not relative.endswith(".jsonl"):
            raise ValueError("无效的会话文件路径")
        return self.files.path(*parts)

    def path(self, user_id, conversation_id, *, created_at=None):
        uid, cid = safe_id(user_id), safe_id(conversation_id)
        if created_at is not None:
            date = datetime.fromisoformat(stamp(created_at))
            filename = f"rollout-{date.strftime('%Y-%m-%dT%H-%M-%S')}-{cid}.jsonl"
            path = self.files.path("sessions", date.strftime("%Y"), date.strftime("%m"), date.strftime("%d"), filename)
        else:
            with self.factory() as db:
                index = db.get(ConversationJournal, cid)
                if index and index.user_id == uid:
                    path = self.rollout_path(index.relative_path)
                elif index:
                    # Never expose another user's global dated rollout through a guessed ID.
                    return self.files.path("sessions", uid, cid + ".jsonl")
                else:
                    path = self._paths.get((uid, cid)) or self.files.path("sessions", uid, cid + ".jsonl")
        self._paths[(uid, cid)] = path
        return path

    def migrate_layout(self):
        """Move legacy rollouts byte-for-byte; recover a move interrupted before SQL commit."""
        with self.files.lock("rollout-migration"):
            with self.factory() as db:
                db.info["journal_suppressed"] = True
                rows = db.execute(select(ConversationJournal, Conversation)
                    .join(Conversation, Conversation.id == ConversationJournal.conversation_id)).all()
                old_directories = set()
                for index, conversation in rows:
                    source = self.rollout_path(index.relative_path)
                    if index.relative_path.startswith("archived_sessions/"):
                        continue
                    target = self.path(index.user_id, index.conversation_id, created_at=conversation.created_at)
                    if source != target:
                        old_directories.add(source.parent)
                        if source.exists():
                            if target.exists():
                                raise RuntimeError("新旧会话文件同时存在，迁移已停止以避免覆盖")
                            target.parent.mkdir(parents=True, exist_ok=True)
                            os.replace(source, target)
                        elif not target.exists():
                            raise RuntimeError("会话原始文件缺失，迁移已停止")
                        index.relative_path = target.relative_to(self.files.root).as_posix()
                db.commit()
                for directory in old_directories:
                    # Only remove empty legacy user directories, never recursively delete records.
                    if directory.parent == self.files.path("sessions"):
                        try:
                            directory.rmdir()
                        except OSError:
                            pass
        self.write_index()

    def write_index(self):
        """A rebuildable Codex-style thread index; SQLite remains the permission boundary."""
        with self.files.lock("session-index"):
            with self.factory() as db:
                rows = db.execute(select(Conversation, ConversationJournal)
                    .join(ConversationJournal, ConversationJournal.conversation_id == Conversation.id)
                    .order_by(Conversation.created_at, Conversation.id)).all()
                content = "".join(json.dumps({"id": row.id, "thread_name": row.title,
                    "updated_at": stamp(row.updated_at), "user_id": row.user_id,
                    "rollout_path": index.relative_path}, ensure_ascii=False) + "\n" for row, index in rows)
            self.files.atomic_write(self.files.path("session_index.jsonl"), content)

    def _read(self, path, *, repair=False):
        if not path.exists():
            return []
        records, offset = [], 0
        mode = "r+b" if repair else "rb"
        with path.open(mode) as handle:
            lines = handle.readlines()
            for index, line in enumerate(lines):
                try:
                    item = json.loads(line)
                    if not isinstance(item, dict) or "event_id" not in item:
                        raise ValueError()
                except (ValueError, UnicodeDecodeError):
                    # A crash may leave only the final append incomplete. Never skip middle corruption.
                    if index != len(lines) - 1 or line.endswith(b"\n"):
                        raise RuntimeError("会话 JSONL 存在损坏记录") from None
                    if repair:
                        handle.seek(offset)
                        handle.truncate()
                        handle.flush()
                        os.fsync(handle.fileno())
                    break
                if repair and not line.endswith(b"\n"):
                    handle.seek(0, os.SEEK_END)
                    handle.write(b"\n")
                records.append(item)
                offset += len(line)
        return records

    def append(self, user_id, conversation_id, kind, payload, *, event_id=None, timestamp=None):
        path = self.path(user_id, conversation_id)
        with self.files.lock("session:" + user_id + ":" + conversation_id):
            records = self._read(path, repair=True)
            eid = event_id or new_id()
            existing = next((row for row in records if row["event_id"] == eid), None)
            if existing:
                return existing
            record = {"seq": len(records) + 1, "event_id": eid, "timestamp": timestamp or stamp(None),
                      "type": kind, "payload": payload}
            path.parent.mkdir(parents=True, exist_ok=True)
            encoded = (json.dumps(record, ensure_ascii=False, default=str) + "\n").encode("utf-8")
            with path.open("ab") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            return record

    def delete(self, user_id, conversation_id, *, relative_path=None):
        with self.files.lock("session:" + user_id + ":" + conversation_id):
            path = self.rollout_path(relative_path) if relative_path else self.path(user_id, conversation_id)
            path.unlink(missing_ok=True)

    def drain(self):
        # File event ids make replay safe if the process dies between append and checkpoint.
        with self.files.lock("outbox"):
            with self.factory() as db:
                rows = db.scalars(select(SessionEvent).where(SessionEvent.delivered.is_(False))
                                  .order_by(SessionEvent.seq)).all()
                deleted_sessions = {(row.user_id, row.conversation_id) for row in rows if row.kind == "session_deleted"}
                for row in rows:
                    if row.kind == "session_deleted":
                        self.delete(row.user_id, row.conversation_id, relative_path=row.payload_json.get("relative_path"))
                    elif (row.user_id, row.conversation_id) not in deleted_sessions:
                        self.append(row.user_id, row.conversation_id, row.kind, row.payload_json,
                                    event_id=row.event_id, timestamp=stamp(row.created_at))
                    db.execute(update(SessionEvent).where(SessionEvent.seq == row.seq)
                               .values(delivered=True, payload_json={}))
                if rows:
                    db.info["journal_suppressed"] = True
                    db.commit()
        if rows:
            self.write_index()

    def events(self, user_id, conversation_id):
        self.drain()
        path = self.path(user_id, conversation_id)
        with self.files.lock("session:" + user_id + ":" + conversation_id):
            return self._read(path)

    @staticmethod
    def message_payload(row):
        return {"id": row.id, "role": row.role, "content": row.content,
                "metadata": row.metadata_json or {}, "created_at": stamp(row.created_at)}

    @staticmethod
    def replay(records):
        messages = OrderedDict()
        for item in records:
            payload = item["payload"]
            if item["type"] == "response_item" and payload.get("type") == "message":
                value = payload["message"]
                messages[value["id"]] = SimpleNamespace(id=value["id"], role=value["role"],
                    content=value["content"], metadata_json=value.get("metadata", {}),
                    created_at=datetime.fromisoformat(value["created_at"]))
            elif item["type"] == "message_deleted":
                messages.pop(payload["id"], None)
        return list(messages.values())

    def messages(self, user_id, conversation_id):
        return self.replay(self.events(user_id, conversation_id))

    def backfill(self):
        """Import existing SQLite history once, without changing original rows."""
        self.migrate_layout()
        with self.factory() as db:
            db.info["journal_suppressed"] = True
            for conversation in db.scalars(select(Conversation).order_by(Conversation.created_at)).all():
                if db.get(ConversationJournal, conversation.id):
                    continue
                path = self.path(conversation.user_id, conversation.id, created_at=conversation.created_at)
                db.add(ConversationJournal(conversation_id=conversation.id, user_id=conversation.user_id,
                    relative_path=path.relative_to(self.files.root).as_posix()))
                db.add(SessionEvent(user_id=conversation.user_id, conversation_id=conversation.id,
                    kind="session_meta", payload_json={"id": conversation.id, "user_id": conversation.user_id, "title": conversation.title,
                        "task_id": conversation.task_id, "created_at": stamp(conversation.created_at)}))
                branch = db.get(ConversationInheritance, conversation.id)
                if branch:
                    db.add(SessionEvent(user_id=conversation.user_id, conversation_id=conversation.id,
                        kind="inherited_context", payload_json={"source_id": branch.source_id,
                            "mode": branch.mode, "context": branch.context}))
                for row in db.scalars(select(Message).where(Message.conversation_id == conversation.id)
                                      .order_by(Message.created_at, Message.id)).all():
                    db.add(SessionEvent(user_id=conversation.user_id, conversation_id=conversation.id,
                        kind="response_item", payload_json={"type": "message", "message": self.message_payload(row)},
                        created_at=row.created_at))
                for row in db.scalars(select(AgentRun).where(AgentRun.conversation_id == conversation.id)
                                      .order_by(AgentRun.created_at, AgentRun.id)).all():
                    self.queue_trace(db, conversation, row)
                task_ids = select(AgentTask.id).where(AgentTask.conversation_id == conversation.id)
                for row in db.scalars(select(AgentTaskEvent).where(AgentTaskEvent.task_id.in_(task_ids))
                                      .order_by(AgentTaskEvent.created_at, AgentTaskEvent.id)).all():
                    db.add(SessionEvent(user_id=conversation.user_id, conversation_id=conversation.id,
                        kind=row.kind if row.kind in {"tool_call", "tool_result"} else "task_event",
                        payload_json={"task_id": row.task_id, "kind": row.kind, "detail": protected_data(row.detail_json)},
                        created_at=row.created_at))
            db.commit()
        self.drain()
        self.write_index()

    def queue_trace(self, db, conversation, run):
        db.add(SessionEvent(user_id=conversation.user_id, conversation_id=conversation.id,
            kind="run_trace", payload_json={"run_id": run.id, "trace": protected_data(run.trace_json)},
            created_at=run.created_at))
        for stage in (run.trace_json or {}).get("stages", []):
            if stage.get("kind") not in {"tool", "retrieval"}:
                continue
            detail = protected_data(stage.get("detail") or {})
            call_id = stage["id"]
            common = {"call_id": call_id, "run_id": run.id, "name": detail.get("tool", stage.get("title"))}
            db.add(SessionEvent(user_id=conversation.user_id, conversation_id=conversation.id,
                kind="tool_call", payload_json={**common, "arguments": {"query": detail.get("query", "")}}))
            if stage.get("status") != "running":
                db.add(SessionEvent(user_id=conversation.user_id, conversation_id=conversation.id,
                    kind="tool_result", payload_json={**common, "status": stage.get("status"), "result": detail}))

    def install(self):
        tracked = (Conversation, ConversationInheritance, Message, AgentRun, AgentTaskEvent)

        @event.listens_for(self.factory, "before_flush")
        def collect(db, context, instances):
            if db.info.get("journal_suppressed"):
                return
            changes = [(row, False) for row in list(db.new) + list(db.dirty)
                       if isinstance(row, tracked) and (row in db.new or db.is_modified(row, include_collections=False))]
            changes.extend((row, True) for row in db.deleted if isinstance(row, tracked))
            owners = {}
            paths = {}
            for row, deleted in changes:
                if isinstance(row, Conversation):
                    owners[row.id] = row
                    if deleted:
                        index = db.get(ConversationJournal, row.id)
                        if index:
                            paths[row.id] = index.relative_path
                elif isinstance(row, (Message, AgentRun, ConversationInheritance)):
                    if row.conversation_id:
                        owners[row.conversation_id] = db.get(Conversation, row.conversation_id)
                else:
                    task = db.get(AgentTask, row.task_id) if row.task_id else None
                    if task and task.conversation_id:
                        owners[task.conversation_id] = db.get(Conversation, task.conversation_id)
            db.info["journal_changes"] = (changes, owners, paths)

        @event.listens_for(self.factory, "after_flush_postexec")
        def enqueue(db, context):
            changes, owners, paths = db.info.pop("journal_changes", ([], {}, {}))
            # The whole-session deletion must be the final event, including ORM cascades.
            changes.sort(key=lambda pair: isinstance(pair[0], Conversation) and pair[1])
            for row, deleted in changes:
                if isinstance(row, Conversation):
                    conversation = row
                elif isinstance(row, (Message, AgentRun, ConversationInheritance)):
                    conversation = owners.get(row.conversation_id)
                    if conversation is None and not deleted:
                        conversation = db.get(Conversation, row.conversation_id)
                else:
                    task = db.get(AgentTask, row.task_id)
                    conversation = (owners.get(task.conversation_id) or db.get(Conversation, task.conversation_id)) if task and task.conversation_id else None
                if conversation is None:
                    continue
                cid, uid = conversation.id, conversation.user_id
                if isinstance(row, Conversation):
                    kind = "session_deleted" if deleted else "session_meta"
                    payload = {"id": cid, "user_id": uid, "title": row.title, "task_id": row.task_id,
                               "pinned": row.pinned, "created_at": stamp(row.created_at)}
                    if deleted:
                        payload["relative_path"] = paths.get(cid)
                    if not deleted and not db.get(ConversationJournal, cid):
                        db.add(ConversationJournal(conversation_id=cid, user_id=uid,
                            relative_path=self.path(uid, cid, created_at=row.created_at).relative_to(self.files.root).as_posix()))
                elif isinstance(row, Message):
                    kind = "message_deleted" if deleted else "response_item"
                    payload = {"id": row.id} if deleted else {"type": "message", "message": self.message_payload(row)}
                elif isinstance(row, ConversationInheritance):
                    kind = "inherited_context"
                    payload = {"source_id": row.source_id, "mode": row.mode, "context": row.context, "deleted": deleted}
                elif isinstance(row, AgentRun):
                    if not deleted:
                        self.queue_trace(db, conversation, row)
                    continue
                elif not deleted:
                    kind = row.kind if row.kind in {"tool_call", "tool_result"} else "task_event"
                    payload = {"task_id": row.task_id, "kind": row.kind, "detail": protected_data(row.detail_json)}
                else:
                    continue
                db.add(SessionEvent(user_id=uid, conversation_id=cid, kind=kind, payload_json=payload))

        @event.listens_for(self.factory, "after_commit")
        def deliver(db):
            if db.info.get("journal_suppressed"):
                return
            try:
                self.drain()
            except (OSError, RuntimeError):
                # The DB transaction has committed. The durable outbox will be retried.
                log.error("Session journal delivery deferred; pending events are retained in SQLite")
