"""Conversation endpoint for the poster multi-agent domain."""

from __future__ import annotations

import json
from concurrent.futures import Future
from threading import Thread
from time import sleep
from types import SimpleNamespace

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import CurrentContext, Db
from app.db.models import AgentRun, Conversation, Message, new_id, utcnow
from app.plugins.poster_agent.trace import poster_trace
from app.runtime.protocol import TaskSpec
from app.schemas.chat import ChatSend, MessageOut

router = APIRouter(prefix="/conversations", tags=["posters"])


def create_poster(conversation_id: str, payload: ChatSend, request: Request, db: Db,
                  context: CurrentContext, *, task_id: str | None = None):
    user_id = context[0].id
    conversation = db.scalar(select(Conversation).where(Conversation.id == conversation_id,
                                                        Conversation.user_id == user_id))
    if conversation is None:
        raise HTTPException(404, "会话不存在")
    if payload.skill is None or payload.skill.id != "poster":
        raise HTTPException(422, "请选择海报设计功能")
    if len(payload.attachment_ids) > 8:
        raise HTTPException(422, "单张海报最多放入 8 张上传图片")
    if len(payload.attachment_ids) != len(payload.attachment_preview_ids):
        raise HTTPException(422, "上传图片缺少本地素材，请重新上传")
    if any(not item for item in payload.attachment_preview_ids):
        raise HTTPException(422, "上传图片缺少本地素材，请重新上传")
    from app.api.routes.conversations import inherited_context
    branch_context = inherited_context(db, conversation_id)
    description = (f"来源会话背景：\n{branch_context[:12000]}\n\n当前海报要求：\n" if branch_context else "") + (payload.content or "请基于上传的图片设计一张精美海报，并完整保留全部图片。")
    for item in payload.text_attachments:
        description += f"\n\n附件《{item.name}》：\n{item.content}"
    spec = TaskSpec(task_id=task_id or new_id(), agent="supervisor", goal=description,
                    inputs={"steps": [{"intent": "poster", "inputs": {
                        "query": description,
                        "image_preview_ids": payload.attachment_preview_ids,
                        "image_names": payload.attachment_names,
                    }}]})
    task = request.app.state.agent_runner.submit(spec, user_id=user_id,
                                                  conversation_id=conversation_id)
    trace = poster_trace(request.app.state.task_manager, spec.task_id, user_id, description)
    if task.status != "completed" or not task.result or len(task.result.artifact_ids) < 3:
        db.add(AgentRun(id=spec.task_id, conversation_id=conversation_id, trace_json=trace))
        db.commit()
        raise HTTPException(502, task.error or "海报设计未完成", headers={"X-Agent-Task-Id": spec.task_id})
    child_id = task.result.outputs["child_task_ids"][-1]
    child = request.app.state.task_manager.get(child_id, user_id=user_id)
    output = child.result.outputs if child.result else {}
    poster = {"htmlArtifactId": task.result.artifact_ids[0],
              "pngArtifactId": task.result.artifact_ids[1],
              "pdfArtifactId": task.result.artifact_ids[2],
              "qualityIssues": output.get("quality_issues", []),
              "imageCount": output.get("asset_count", 0)}
    attachments = [{"type": "image", "id": file_id,
                    "name": payload.attachment_names[index] if index < len(payload.attachment_names) else "图片",
                    "previewId": payload.attachment_preview_ids[index]}
                   for index, file_id in enumerate(payload.attachment_ids)]
    attachments.extend({"type": "text", "name": item.name, "content": item.content,
                        "mimeType": item.mime_type} for item in payload.text_attachments)
    user_message = Message(conversation_id=conversation_id, role="user", content=payload.content,
                           metadata_json={"skill": payload.skill.model_dump(by_alias=True),
                                          "attachments": attachments})
    assistant_message = Message(conversation_id=conversation_id, role="assistant",
                                content=task.result.summary,
                                metadata_json={"poster": poster, "agentTaskId": spec.task_id})
    db.add_all([user_message, assistant_message,
                AgentRun(id=spec.task_id, conversation_id=conversation_id, trace_json=trace)])
    if conversation.title == "新会话":
        conversation.title = (payload.content.strip() or "海报设计")[:160]
    conversation.updated_at = utcnow()
    db.commit()
    return {"userMessage": MessageOut.from_record(user_message).model_dump(by_alias=True, mode="json"),
            "assistantMessage": MessageOut.from_record(assistant_message).model_dump(by_alias=True, mode="json"),
            "trace": trace}


@router.post("/{conversation_id}/posters/stream")
def stream_poster(conversation_id: str, payload: ChatSend, request: Request, db: Db,
                  context: CurrentContext):
    user_id = context[0].id
    if not db.scalar(select(Conversation.id).where(Conversation.id == conversation_id,
                                                    Conversation.user_id == user_id)):
        raise HTTPException(404, "会话不存在")
    db.rollback()
    task_id = new_id()
    manager = request.app.state.task_manager

    def event(kind: str, **data):
        return json.dumps({"type": kind, **data}, ensure_ascii=False) + "\n"

    def stream():
        future = Future()

        def execute():
            try:
                with request.app.state.session_factory() as worker_db:
                    result = create_poster(conversation_id, payload, request, worker_db,
                                           (SimpleNamespace(id=user_id), None), task_id=task_id)
                    future.set_result(result)
            except BaseException as exc:
                future.set_exception(exc)

        Thread(target=execute, name="mindpilot-poster-stream", daemon=True).start()
        last = ""
        while not future.done():
            trace = poster_trace(manager, task_id, user_id, payload.content)
            signature = json.dumps(trace, sort_keys=True, ensure_ascii=False)
            if signature != last:
                yield event("trace", trace=trace)
                last = signature
            sleep(0.2)
        trace = poster_trace(manager, task_id, user_id, payload.content)
        if json.dumps(trace, sort_keys=True, ensure_ascii=False) != last:
            yield event("trace", trace=trace)
        try:
            result = future.result()
        except HTTPException as exc:
            yield event("error", message=str(exc.detail), trace=trace, taskId=task_id)
            return
        except Exception as exc:
            yield event("error", message=str(exc), trace=trace, taskId=task_id)
            return
        yield event("done", **result)

    return StreamingResponse(stream(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
