"""Conversation endpoints for the editable AI drawing skill."""

from __future__ import annotations

import json
from concurrent.futures import Future
from threading import Thread
from time import perf_counter, sleep
from types import SimpleNamespace

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import Field
from sqlalchemy import select

from app.api.deps import CurrentContext, Db
from app.db.models import AgentRun, AgentTask, Conversation, Message, new_id, utcnow
from app.schemas.base import CamelModel
from app.schemas.chat import ChatSend, MessageOut
from app.services.text_generation import TextGenerationError
from app.runtime.protocol import TaskSpec
from app.plugins.diagram_agent.trace import drawing_trace
from app.skills.ai_drawing import is_edit_request
from app.skills.drawing_engine import DiagramError, clean_label, parse_model
from app.skills.drawing_preview import render_preview

router = APIRouter(prefix="/conversations", tags=["diagrams"])


class DiagramSave(CamelModel):
    xml: str = Field(min_length=1, max_length=2_000_000)
    base_version: int | None = Field(default=None, ge=1)


class DiagramTurn(CamelModel):
    content: str = Field(min_length=1, max_length=3000)
    xml: str = Field(min_length=1, max_length=2_000_000)
    base_version: int = Field(ge=1)


def _owned(db: Db, user_id: str, conversation_id: str) -> Conversation:
    item = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id))
    if item is None:
        raise HTTPException(404, "会话不存在")
    return item


def _diagram_meta(kind: str, xml: str, *, version: int = 1) -> dict:
    parse_model(xml)
    return {"type": kind, "xml": xml, "svg": render_preview(xml), "version": version,
            "previewVersion": 2}


def _drawing_steps(prompt: str, kind: str, result: dict, elapsed_ms: int) -> list[dict]:
    noun = "流程图" if kind == "flowchart" else "思维导图"
    model = parse_model(result["xml"])
    root = model.find("root")
    cells = root.findall("mxCell") if root is not None else []
    nodes = {cell.get("id"): clean_label(cell.get("value")) for cell in cells if cell.get("vertex") == "1"}
    edges = [cell for cell in cells if cell.get("edge") == "1"]
    branches = [label for cell in cells if cell.get("vertex") == "1"
                and "rhombus" in cell.get("style", "")
                if (label := clean_label(cell.get("value")))]
    connections = [{"source": nodes.get(edge.get("source"), "节点"),
                    "target": nodes.get(edge.get("target"), "节点"),
                    "label": clean_label(edge.get("value"))} for edge in edges]
    paths = [f"{item['source']} → {item['target']}" + (f"（{item['label']}）" if item["label"] else "")
             for item in connections[:8]]
    node_details = "\n".join(f"• {label}" for label in list(nodes.values())[:14])
    path_details = "\n".join(f"• {path}" for path in paths)
    return [
        {"kind": "input", "title": "理解绘图目标", "detail": f"根据描述确定绘制{noun}：{prompt[:120]}", "elapsedMs": 1},
        {"kind": "nodes", "title": "内容规划 · 节点与信息", "count": len(nodes), "items": list(nodes.values()),
         "detail": f"确定 {len(nodes)} 个节点：\n{node_details or '无'}" +
         (f"\n…另有 {len(nodes) - 14} 个节点" if len(nodes) > 14 else ""), "elapsedMs": elapsed_ms},
        {"kind": "connections", "title": "排版设计 · 分支与连接", "count": len(edges),
         "items": connections, "decisions": branches,
         "detail": f"建立 {len(edges)} 条连接。" +
         (f"\n关键判断：{'、'.join(branches[:5])}" if branches else "") +
         (f"\n主要路径：\n{path_details}" if paths else "") +
         (f"\n…另有 {len(edges) - 8} 条连接" if len(edges) > 8 else ""), "elapsedMs": elapsed_ms},
        {"kind": "output", "title": "生成可编辑图表", "detail": "已校验 draw.io XML 并生成当前会话的预览，可以继续对话修改或打开编辑器调整。",
         "elapsedMs": elapsed_ms},
    ]


@router.post("/{conversation_id}/diagrams")
def create_diagram(conversation_id: str, payload: ChatSend, request: Request, db: Db,
                   context: CurrentContext, *, task_id: str | None = None):
    conversation = _owned(db, context[0].id, conversation_id)
    kind = payload.skill.id if payload.skill else ""
    if kind not in {"flowchart", "mindmap"}:
        raise HTTPException(422, "请选择流程图或思维导图技能")
    if payload.attachment_ids:
        raise HTTPException(422, "绘图暂不支持图片附件，请使用文字描述")
    from app.api.routes.conversations import inherited_context
    branch_context = inherited_context(db, conversation_id)
    description = (f"来源会话背景：\n{branch_context[:12000]}\n\n当前绘图要求：\n" if branch_context else "") + payload.content
    for attachment in payload.text_attachments:
        description += f"\n\n附件 {attachment.name}:\n{attachment.content}"
    if not description.strip():
        raise HTTPException(422, "请描述要绘制的内容")
    started = perf_counter()
    task_spec = None
    try:
        previous = db.scalars(select(Message).where(Message.conversation_id == conversation_id,
                                                    Message.role == "assistant").order_by(Message.created_at.desc(), Message.id.desc())).all()
        previous_diagram = next((item.metadata_json["diagram"] for item in previous
                                 if isinstance(item.metadata_json.get("diagram"), dict)
                                 and item.metadata_json["diagram"].get("type") == kind), None)
        editing = bool(previous_diagram and is_edit_request(payload.content))
        inputs = {"query": description, "kind": kind}
        if editing:
            if previous_diagram.get("artifactId"):
                inputs["previous_diagram_artifact_id"] = previous_diagram["artifactId"]
        task_spec = TaskSpec(task_id=task_id or new_id(), agent="supervisor", goal=description,
                             inputs={"steps": [{"intent": "diagram_edit" if editing else kind,
                                                "inputs": inputs}]})
        runner = request.app.state.agent_runner
        if editing and not previous_diagram.get("artifactId"):
            # Import a legacy diagram once, then pass only its artifact ID downstream.
            manager = request.app.state.task_manager
            manager.create(task_spec, user_id=context[0].id, conversation_id=conversation_id)
            old_id = request.app.state.artifact_store.save_text(
                previous_diagram["xml"], user_id=context[0].id, task_id=task_spec.task_id,
                kind="diagram", filename="previous.drawio", mime_type="application/xml",
                version=int(previous_diagram.get("version", 1)))
            task_spec.inputs["steps"][0]["inputs"]["previous_diagram_artifact_id"] = old_id
            manager.update_queued_inputs(task_spec.task_id, task_spec.inputs)
            task = runner.run(task_spec.task_id)
        else:
            task = runner.submit(task_spec, user_id=context[0].id, conversation_id=conversation_id)
        if task.status != "completed" or not task.result or len(task.result.artifact_ids) < 2:
            raise DiagramError(task.error or "绘图 Agent 未完成任务")
        child_id = task.result.outputs["child_task_ids"][-1]
        child_result = request.app.state.task_manager.get(child_id, user_id=context[0].id).result
        _, xml_bytes = request.app.state.artifact_store.read(task.result.artifact_ids[0], user_id=context[0].id)
        result = {"xml": xml_bytes.decode("utf-8"), "model": child_result.outputs["model"],
                  "summary": child_result.summary, "nodes": child_result.outputs["nodes"],
                  "edges": child_result.outputs["edges"]}
        diagram = _diagram_meta(kind, result["xml"])
        diagram.update({"artifactId": task.result.artifact_ids[0],
                        "previewArtifactId": task.result.artifact_ids[1]})
    except (DiagramError, TextGenerationError, RuntimeError) as exc:
        headers = None
        if task_spec is not None:
            manager = request.app.state.task_manager
            try:
                manager.get(task_spec.task_id, user_id=context[0].id)
            except KeyError:
                pass
            else:
                trace = drawing_trace(manager, task_spec.task_id, context[0].id,
                                      payload.content)
                db.add(AgentRun(id=task_spec.task_id, conversation_id=conversation_id,
                                trace_json=trace))
                db.commit()
                headers = {"X-Agent-Task-Id": task_spec.task_id}
        raise HTTPException(502, str(exc), headers=headers) from exc
    skill_meta = payload.skill.model_dump(by_alias=True)
    user_message = Message(conversation_id=conversation_id, role="user", content=payload.content,
                           metadata_json={"skill": skill_meta,
                                          "attachments": [{"type": "text", "name": item.name, "content": item.content,
                                                           "mimeType": item.mime_type} for item in payload.text_attachments]})
    noun = "流程图" if kind == "flowchart" else "思维导图"
    elapsed_ms = round((perf_counter() - started) * 1000)
    drawing_steps = _drawing_steps(payload.content, kind, result, elapsed_ms)
    fallback_note = (" 排版优化请求超时，已保留可编辑的上一版图稿。"
                     if child_result.outputs.get("review", {}).get("fallback_reason") else "")
    assistant_message = Message(conversation_id=conversation_id, role="assistant",
                                content=f"已{'更新' if editing else '生成'}{noun}，可以下载或在 draw.io 中编辑。"
                                        + fallback_note,
                                metadata_json={"diagram": diagram, "model": result["model"],
                                               "agentTaskId": task.task_id,
                                               "latencyMs": elapsed_ms, "drawingSteps": drawing_steps})
    trace = drawing_trace(request.app.state.task_manager, task.task_id,
                          context[0].id, payload.content)
    db.add_all([user_message, assistant_message, AgentRun(id=task.task_id, conversation_id=conversation_id, trace_json=trace)])
    if conversation.title == "新会话":
        conversation.title = (payload.content.strip() or noun)[:160]
    conversation.updated_at = utcnow()
    db.commit()
    return {"userMessage": MessageOut.from_record(user_message).model_dump(by_alias=True, mode="json"),
            "assistantMessage": MessageOut.from_record(assistant_message).model_dump(by_alias=True, mode="json"),
            "trace": trace}


@router.post("/{conversation_id}/diagrams/stream")
def stream_diagram(conversation_id: str, payload: ChatSend, request: Request, db: Db, context: CurrentContext):
    user_id = context[0].id
    _owned(db, user_id, conversation_id)
    if not payload.skill or payload.skill.id not in {"flowchart", "mindmap"}:
        raise HTTPException(422, "请选择流程图或思维导图技能")
    # The long-running worker owns a separate session; release this read transaction.
    db.rollback()

    def event(kind: str, **values) -> str:
        return json.dumps({"type": kind, **values}, ensure_ascii=False, separators=(",", ":")) + "\n"

    task_id = new_id()
    manager = request.app.state.task_manager

    def stream():
        yield event("progress", step={"title": "理解绘图目标", "detail": "正在解析描述与图表类型…", "status": "complete"})
        yield event("progress", step={"title": "内容规划 · 节点与信息", "detail": "正在确定节点、判断条件和连接关系…", "status": "running"})
        yield event("trace", trace=drawing_trace(manager, task_id, user_id, payload.content))
        future: Future = Future()

        def execute():
            try:
                with request.app.state.session_factory() as worker_db:
                    future.set_result(create_diagram(conversation_id, payload, request,
                                                     worker_db, (SimpleNamespace(id=user_id), None),
                                                     task_id=task_id))
            except BaseException as exc:
                future.set_exception(exc)

        Thread(target=execute, name="mindpilot-drawing-stream", daemon=True).start()
        last_signature = ""
        while not future.done():
            trace = drawing_trace(manager, task_id, user_id, payload.content)
            signature = json.dumps(trace, ensure_ascii=False, sort_keys=True)
            if signature != last_signature:
                yield event("trace", trace=trace)
                last_signature = signature
            sleep(0.2)
        trace = drawing_trace(manager, task_id, user_id, payload.content)
        if json.dumps(trace, ensure_ascii=False, sort_keys=True) != last_signature:
            yield event("trace", trace=trace)
        try:
            result = future.result()
        except HTTPException as exc:
            yield event("error", message=str(exc.detail),
                        taskId=task_id, trace=trace)
            return
        except Exception as exc:
            yield event("error", message=str(exc), taskId=task_id, trace=trace)
            return
        steps = result["assistantMessage"]["metadata"]["drawingSteps"]
        for step in steps[1:]:
            yield event("progress", step={**step, "status": "complete"})
        yield event("done", **result)

    return StreamingResponse(stream(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.put("/{conversation_id}/messages/{message_id}/diagram", response_model=MessageOut)
def save_diagram(conversation_id: str, message_id: str, payload: DiagramSave, request: Request, db: Db, context: CurrentContext):
    conversation = _owned(db, context[0].id, conversation_id)
    message = db.scalar(select(Message).where(Message.id == message_id, Message.conversation_id == conversation_id))
    old = message.metadata_json.get("diagram") if message and message.role == "assistant" else None
    if not isinstance(old, dict):
        raise HTTPException(404, "图表消息不存在")
    if payload.base_version is not None and payload.base_version != int(old.get("version", 1)):
        raise HTTPException(409, "图表已在其他位置更新，请重新打开编辑器")
    try:
        diagram = _diagram_meta(old["type"], payload.xml, version=int(old.get("version", 1)) + 1)
    except (DiagramError, KeyError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    task_id = message.metadata_json.get("agentTaskId")
    if task_id:
        try:
            request_task = db.get(AgentTask, task_id)
            if request_task is None or request_task.user_id != context[0].id:
                raise KeyError(task_id)
            artifacts = request_task.result_json.get("artifact_ids", [])
            old_sources = []
            if artifacts:
                old_artifact, _ = request.app.state.artifact_store.read(artifacts[0], user_id=context[0].id)
                old_sources = old_artifact.source_ids_json
            store = request.app.state.artifact_store
            diagram["artifactId"] = store.save_text(diagram["xml"], user_id=context[0].id,
                                                     task_id=task_id, kind="diagram", filename="diagram.drawio",
                                                     mime_type="application/xml", source_ids=old_sources,
                                                     version=diagram["version"])
            diagram["previewArtifactId"] = store.save_text(diagram["svg"], user_id=context[0].id,
                                                            task_id=task_id, kind="preview", filename="diagram.svg",
                                                            mime_type="image/svg+xml", source_ids=old_sources,
                                                            version=diagram["version"])
        except KeyError:
            raise HTTPException(404, "绘图任务不存在") from None
    message.metadata_json = {**message.metadata_json, "diagram": diagram}
    conversation.updated_at = utcnow()
    db.commit()
    return MessageOut.from_record(message)


@router.post("/{conversation_id}/messages/{message_id}/diagram/turns")
def edit_diagram_turn(conversation_id: str, message_id: str, payload: DiagramTurn,
                      request: Request, db: Db, context: CurrentContext):
    """Apply one AI edit to the editor's latest XML and persist a new diagram version."""
    conversation = _owned(db, context[0].id, conversation_id)
    message = db.scalar(select(Message).where(Message.id == message_id,
                                              Message.conversation_id == conversation_id))
    old = message.metadata_json.get("diagram") if message and message.role == "assistant" else None
    if not isinstance(old, dict):
        raise HTTPException(404, "图表消息不存在")
    if payload.base_version != int(old.get("version", 1)):
        raise HTTPException(409, "图表已更新，请重新打开后继续修改")
    try:
        parse_model(payload.xml)
    except DiagramError as exc:
        raise HTTPException(422, str(exc)) from exc
    manager = request.app.state.task_manager
    store = request.app.state.artifact_store
    history = message.metadata_json.get("editorTurns") or []
    if not isinstance(history, list):
        history = []
    spec = TaskSpec(agent="supervisor", goal=payload.content,
                    inputs={"steps": [{"intent": "diagram_edit", "inputs": {
                        "query": payload.content, "kind": old.get("type", "flowchart"),
                        "editor_history": history[-8:],
                        "base_version": payload.base_version,
                    }}]})
    try:
        manager.create(spec, user_id=context[0].id, conversation_id=conversation_id)
        source_ids = []
        if old.get("artifactId"):
            old_artifact, _ = store.read(old["artifactId"], user_id=context[0].id)
            source_ids = old_artifact.source_ids_json
        draft_id = store.save_text(payload.xml, user_id=context[0].id,
                                   task_id=spec.task_id, kind="editor_draft",
                                   filename="editor-draft.drawio", mime_type="application/xml",
                                   source_ids=source_ids, version=payload.base_version)
        spec.inputs["steps"][0]["inputs"]["previous_diagram_artifact_id"] = draft_id
        manager.update_queued_inputs(spec.task_id, spec.inputs)
        task = request.app.state.agent_runner.run(spec.task_id)
        if task.status != "completed" or not task.result or len(task.result.artifact_ids) < 2:
            raise DiagramError(task.error or "绘图 Agent 未能完成修改")
        child_id = task.result.outputs["child_task_ids"][-1]
        child = manager.get(child_id, user_id=context[0].id).result
        _, xml_bytes = store.read(task.result.artifact_ids[0], user_id=context[0].id)
        next_xml = xml_bytes.decode("utf-8")
        diagram = _diagram_meta(old.get("type", "flowchart"), next_xml,
                                version=payload.base_version + 1)
        diagram.update({"artifactId": task.result.artifact_ids[0],
                        "previewArtifactId": task.result.artifact_ids[1]})
    except (DiagramError, TextGenerationError, RuntimeError, KeyError, ValueError) as exc:
        raise HTTPException(502, str(exc)) from exc
    turns = [*history, {"role": "user", "content": payload.content},
             {"role": "assistant", "content": child.summary}][-20:]
    message.metadata_json = {**message.metadata_json, "diagram": diagram,
                             "editorTurns": turns, "agentTaskId": task.task_id}
    conversation.updated_at = utcnow()
    db.commit()
    return {"message": MessageOut.from_record(message).model_dump(by_alias=True, mode="json"),
            "summary": child.summary, "operations": child.outputs.get("operations", []),
            "taskId": task.task_id}
