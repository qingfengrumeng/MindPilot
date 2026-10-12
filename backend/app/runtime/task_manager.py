"""Durable task state transitions and ordered execution events."""

from __future__ import annotations

from sqlalchemy import select

from app.core.security import utcnow
from app.db.models import AgentTask, AgentTaskEvent
from app.runtime.protocol import TaskResult, TaskSnapshot, TaskSpec


_TRANSITIONS = {
    "queued": {"running", "waiting", "cancelled"},
    "running": {"completed", "failed", "waiting", "cancelled"},
    "waiting": {"queued", "running", "cancelled"},
    "failed": {"queued"},
    "completed": set(),
    "cancelled": set(),
}


class TaskManager:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def create(self, spec: TaskSpec, *, user_id: str, conversation_id: str | None = None) -> TaskSnapshot:
        with self.session_factory() as db:
            if spec.parent_task_id:
                parent = db.get(AgentTask, spec.parent_task_id)
                if parent is None or parent.user_id != user_id or parent.conversation_id != conversation_id:
                    raise ValueError("Parent task does not belong to this user and conversation")
            if db.get(AgentTask, spec.task_id):
                raise ValueError("Task id already exists")
            row = AgentTask(id=spec.task_id, user_id=user_id, conversation_id=conversation_id,
                            parent_task_id=spec.parent_task_id, agent_id=spec.agent, goal=spec.goal,
                            inputs_json=spec.inputs, constraints_json=spec.constraints,
                            status="queued", result_json={}, attempt=1)
            db.add(row)
            db.add(AgentTaskEvent(task_id=row.id, kind="created",
                                  detail_json={"agent": row.agent_id, "parent_task_id": row.parent_task_id}))
            db.commit()
            return self._snapshot(row)

    @staticmethod
    def _snapshot(row: AgentTask) -> TaskSnapshot:
        result = TaskResult.model_validate(row.result_json) if row.result_json else None
        return TaskSnapshot(task_id=row.id, parent_task_id=row.parent_task_id, agent=row.agent_id,
                            goal=row.goal, status=row.status, attempt=row.attempt, result=result, error=row.error)

    def get(self, task_id: str, *, user_id: str | None = None) -> TaskSnapshot:
        with self.session_factory() as db:
            row = db.get(AgentTask, task_id)
            if row is None or (user_id is not None and row.user_id != user_id):
                raise KeyError(task_id)
            return self._snapshot(row)

    def spec(self, task_id: str) -> tuple[TaskSpec, str, str | None]:
        with self.session_factory() as db:
            row = db.get(AgentTask, task_id)
            if row is None:
                raise KeyError(task_id)
            return (TaskSpec(task_id=row.id, agent=row.agent_id, goal=row.goal,
                             inputs=row.inputs_json, constraints=row.constraints_json,
                             parent_task_id=row.parent_task_id), row.user_id, row.conversation_id)

    def update_queued_inputs(self, task_id: str, inputs: dict) -> None:
        with self.session_factory() as db:
            row = db.get(AgentTask, task_id)
            if row is None or row.status != "queued":
                raise ValueError("Only queued task inputs can be updated")
            row.inputs_json = inputs
            row.updated_at = utcnow()
            db.commit()

    def event(self, task_id: str, kind: str, detail: dict | None = None) -> None:
        with self.session_factory() as db:
            db.add(AgentTaskEvent(task_id=task_id, kind=kind, detail_json=detail or {}))
            db.commit()

    def events(self, task_id: str, *, user_id: str) -> list[dict]:
        self.get(task_id, user_id=user_id)
        with self.session_factory() as db:
            rows = db.scalars(select(AgentTaskEvent).where(AgentTaskEvent.task_id == task_id)
                              .order_by(AgentTaskEvent.created_at, AgentTaskEvent.id)).all()
            return [{"id": row.id, "kind": row.kind, "detail": row.detail_json,
                     "createdAt": row.created_at.isoformat()} for row in rows]

    def children(self, task_id: str, *, user_id: str) -> list[TaskSnapshot]:
        self.get(task_id, user_id=user_id)
        with self.session_factory() as db:
            rows = db.scalars(select(AgentTask).where(AgentTask.parent_task_id == task_id)
                              .order_by(AgentTask.created_at, AgentTask.id)).all()
            return [self._snapshot(row) for row in rows]

    def transition(self, task_id: str, status: str, *, error: str | None = None,
                   result: TaskResult | None = None) -> TaskSnapshot:
        with self.session_factory() as db:
            row = db.get(AgentTask, task_id)
            if row is None:
                raise KeyError(task_id)
            if status not in _TRANSITIONS[row.status]:
                raise ValueError(f"Invalid task transition: {row.status} -> {status}")
            row.status = status
            row.updated_at = utcnow()
            row.error = error
            if result is not None:
                row.result_json = result.model_dump(mode="json")
            db.add(AgentTaskEvent(task_id=task_id, kind="status", detail_json={"status": status,
                                                                               **({"error": error} if error else {})}))
            db.commit()
            return self._snapshot(row)

    def finish(self, task_id: str, result: TaskResult) -> TaskSnapshot:
        if self.get(task_id).status == "cancelled":
            return self.get(task_id)
        try:
            return self.transition(task_id, result.status, error=result.error, result=result)
        except ValueError:
            snapshot = self.get(task_id)
            if snapshot.status == "cancelled":
                return snapshot
            raise

    def recover_interrupted(self) -> int:
        """A restarted process cannot resume an in-flight Python call; make it retryable."""
        with self.session_factory() as db:
            rows = db.scalars(select(AgentTask).where(AgentTask.status == "running")).all()
            for row in rows:
                row.status = "waiting"
                row.error = "服务重启中断了运行，请重试"
                row.updated_at = utcnow()
                db.add(AgentTaskEvent(task_id=row.id, kind="interrupted",
                                      detail_json={"reason": "server_restart"}))
            db.commit()
            return len(rows)

    def cancel(self, task_id: str, *, user_id: str) -> TaskSnapshot:
        snapshot = self.get(task_id, user_id=user_id)
        if snapshot.status in {"completed", "failed", "cancelled"}:
            return snapshot
        return self.transition(task_id, "cancelled")

    def retry(self, task_id: str, *, user_id: str) -> TaskSnapshot:
        self.get(task_id, user_id=user_id)
        with self.session_factory() as db:
            row = db.get(AgentTask, task_id)
            if row.status not in {"failed", "waiting"}:
                raise ValueError("Only failed or waiting tasks can be retried")
            row.status = "queued"
            row.error = None
            row.result_json = {}
            row.attempt += 1
            row.updated_at = utcnow()
            db.add(AgentTaskEvent(task_id=task_id, kind="retry", detail_json={"attempt": row.attempt}))
            db.commit()
            return self._snapshot(row)
