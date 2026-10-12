"""Public task protocol, capability catalog and artifact retrieval."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from urllib.parse import quote
import re

from app.api.deps import CurrentContext, Db
from app.db.models import Conversation
from app.runtime.protocol import TaskSpec


router = APIRouter(tags=["agent-runtime"])


class TaskRequest(TaskSpec):
    conversation_id: str | None = None
    wait: bool = True


def _owned_conversation(db: Db, user_id: str, conversation_id: str | None):
    if conversation_id and not db.scalar(select(Conversation.id).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id)):
        raise HTTPException(404, "会话不存在")


@router.get("/agent-modules")
def modules(request: Request, context: CurrentContext):
    request.app.state.agent_registry.discover()
    request.app.state.skill_registry.discover()
    return {"agents": request.app.state.agent_registry.summaries(),
            "skills": request.app.state.skill_registry.summaries()}


@router.post("/agent-tasks")
def create_task(payload: TaskRequest, request: Request, db: Db, context: CurrentContext):
    user_id = context[0].id
    _owned_conversation(db, user_id, payload.conversation_id)
    if payload.parent_task_id:
        raise HTTPException(422, "子任务只能由运行平台创建")
    spec = TaskSpec.model_validate(payload.model_dump(exclude={"conversation_id", "wait"}))
    try:
        runner = request.app.state.agent_runner
        snapshot = (runner.submit(spec, user_id=user_id, conversation_id=payload.conversation_id)
                    if payload.wait else runner.enqueue(spec, user_id=user_id,
                                                        conversation_id=payload.conversation_id))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return snapshot.model_dump(mode="json")


@router.get("/agent-modules/{agent_id}")
def module_detail(agent_id: str, request: Request, context: CurrentContext):
    try:
        return request.app.state.agent_registry.details(agent_id)
    except KeyError:
        raise HTTPException(404, "Agent 插件不存在") from None


@router.get("/agent-tasks/{task_id}")
def get_task(task_id: str, request: Request, context: CurrentContext):
    try:
        manager = request.app.state.task_manager
        snapshot = manager.get(task_id, user_id=context[0].id)
        return {**snapshot.model_dump(mode="json"),
                "events": manager.events(task_id, user_id=context[0].id),
                "children": [item.model_dump(mode="json") for item in
                             manager.children(task_id, user_id=context[0].id)]}
    except KeyError:
        raise HTTPException(404, "任务不存在") from None


@router.get("/agent-tasks/{task_id}/trace")
def get_task_trace(task_id: str, request: Request, context: CurrentContext):
    """Return one ordered timeline across the parent task and every child task."""
    manager = request.app.state.task_manager
    user_id = context[0].id
    try:
        manager.get(task_id, user_id=user_id)
    except KeyError:
        raise HTTPException(404, "任务不存在") from None
    pending = [task_id]
    timeline = []
    while pending:
        current_id = pending.pop(0)
        snapshot = manager.get(current_id, user_id=user_id)
        pending.extend(child.task_id for child in manager.children(current_id, user_id=user_id))
        timeline.extend({"task_id": current_id, "parent_task_id": snapshot.parent_task_id,
                         "agent": snapshot.agent, **event}
                        for event in manager.events(current_id, user_id=user_id))
    timeline.sort(key=lambda event: (event["createdAt"], event["id"]))
    return {"task_id": task_id, "events": timeline}


@router.post("/agent-tasks/{task_id}/cancel")
def cancel_task(task_id: str, request: Request, context: CurrentContext):
    try:
        return request.app.state.task_manager.cancel(task_id, user_id=context[0].id).model_dump(mode="json")
    except KeyError:
        raise HTTPException(404, "任务不存在") from None


@router.get("/agent-tasks/{task_id}/artifacts")
def task_artifacts(task_id: str, request: Request, context: CurrentContext):
    try:
        manager = request.app.state.task_manager
        manager.get(task_id, user_id=context[0].id)
    except KeyError:
        raise HTTPException(404, "任务不存在") from None
    task_ids = [task_id, *(item.task_id for item in manager.children(task_id, user_id=context[0].id))]
    store = request.app.state.artifact_store
    return {"items": [artifact for child_id in task_ids
                      for artifact in store.list_for_task(child_id, user_id=context[0].id)]}


@router.post("/agent-tasks/{task_id}/retry")
def retry_task(task_id: str, request: Request, context: CurrentContext):
    try:
        request.app.state.agent_registry.discover()
        request.app.state.skill_registry.discover()
        request.app.state.task_manager.retry(task_id, user_id=context[0].id)
        return request.app.state.agent_runner.run(task_id).model_dump(mode="json")
    except KeyError:
        raise HTTPException(404, "任务不存在") from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/agent-tasks/{task_id}/run")
def run_queued_task(task_id: str, request: Request, context: CurrentContext):
    try:
        request.app.state.task_manager.get(task_id, user_id=context[0].id)
        return request.app.state.agent_runner.run(task_id).model_dump(mode="json")
    except KeyError:
        raise HTTPException(404, "任务不存在") from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/agent-artifacts/{artifact_id}")
def get_artifact(artifact_id: str, request: Request, context: CurrentContext):
    try:
        row, data = request.app.state.artifact_store.read(artifact_id, user_id=context[0].id)
    except KeyError:
        raise HTTPException(404, "产物不存在") from None
    fallback = re.sub(r"[^A-Za-z0-9._-]", "_", row.filename)
    disposition = f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{quote(row.filename)}'
    return Response(data, media_type=row.mime_type, headers={"Content-Disposition": disposition})
