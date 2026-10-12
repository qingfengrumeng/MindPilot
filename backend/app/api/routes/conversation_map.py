"""A per-user visual conversation board and durable conversation branches."""
import json
import re
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentContext, Db
from app.core.model_runtime import require_runtime_model
from app.db.models import AgentTask, Conversation, ConversationInheritance, ConversationMap, Message, utcnow
from app.schemas.chat import ConversationOut
from app.schemas.base import CamelModel
from app.services.text_generation import TextGenerationError, complete_text

router = APIRouter(prefix="/conversation-map", tags=["conversation-map"])


class BoardState(BaseModel):
    nodes: dict[str, dict] = Field(default_factory=dict)
    groups: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)
    viewport: dict = Field(default_factory=lambda: {"x": 0, "y": 0, "zoom": 1})
    synapse: dict = Field(default_factory=dict)


class BranchRequest(CamelModel):
    source_id: str | None = Field(default=None, max_length=36)
    mode: Literal["none", "digest", "full"] = "none"
    title: str = Field(default="新会话", min_length=1, max_length=160)
    task_id: str = Field(default="general", max_length=80)
    context: str | None = Field(default=None, max_length=60000)
    source_message_id: str | None = Field(default=None, max_length=80)


class BranchPreviewRequest(CamelModel):
    source_id: str
    mode: Literal["none", "digest", "full"]


class InjectRequest(CamelModel):
    source_id: str
    target_id: str
    mode: Literal["digest", "full"]


def owned(db, user_id, conversation_id):
    item = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id))
    if not item:
        raise HTTPException(404, "会话不存在")
    return item


def clean_text(value, limit=500):
    plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", str(value or ""))
    plain = re.sub(r"[〔【\[]\s*网页\s*\d+\s*[〕】\]]", "", plain)
    plain = re.sub(r"[*_`#>]+", "", plain)
    plain = re.sub(r"\s+", " ", plain)
    return re.sub(r"\s+([，。；：！？、])", r"\1", plain).strip()[:limit]


def source_messages(db, source_id):
    return db.scalars(select(Message).where(Message.conversation_id == source_id,
                                            Message.role.in_(("user", "assistant")))
                      .order_by(Message.created_at, Message.id)).all()


def digest_fallback(conversation, messages):
    latest_user = next((item for item in reversed(messages) if item.role == "user"), None)
    latest_answer = next((item for item in reversed(messages) if item.role == "assistant"), None)
    return {"summary": clean_text(latest_answer.content if latest_answer else (latest_user.content if latest_user else conversation.title), 220),
            "keyFindings": "", "nextStep": ""}


@router.get("")
def get_board(db: Db, context: CurrentContext):
    user_id = context[0].id
    board = db.get(ConversationMap, user_id)
    conversations = db.scalars(select(Conversation).where(Conversation.user_id == user_id)
                               .order_by(Conversation.updated_at.desc())).all()
    latest_message_id = (select(Message.id)
                         .where(Message.conversation_id == Conversation.id,
                                Message.role.in_(("user", "assistant")))
                         .order_by(Message.created_at.desc(), Message.id.desc())
                         .limit(1).correlate(Conversation).scalar_subquery())
    last_messages = {conversation_id: (role, content) for conversation_id, role, content in db.execute(
        select(Conversation.id, Message.role, Message.content)
        .outerjoin(Message, Message.id == latest_message_id)
        .where(Conversation.user_id == user_id)
    ).all() if role}
    used_features = {item.id for item in conversations if item.task_id and item.task_id != "general"}
    for conversation_id, metadata in db.execute(
        select(Message.conversation_id, Message.metadata_json)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.user_id == user_id, Message.role == "user")
    ):
        skill = (metadata or {}).get("skill")
        if isinstance(skill, dict) and skill.get("id") and skill["id"] != "general":
            used_features.add(conversation_id)
    previews = {}
    task_status = {}
    for task in db.scalars(select(AgentTask).where(AgentTask.user_id == user_id,
                                                    AgentTask.status.in_(("queued", "running", "waiting")))
                           .order_by(AgentTask.updated_at.desc())).all():
        if task.conversation_id and task.conversation_id not in task_status:
            task_status[task.conversation_id] = "running" if task.status == "running" else "waiting"
    for item in conversations:
        latest = last_messages.get(item.id)
        previews[item.id] = {"summary": clean_text(latest[1] if latest else "新会话，尚无内容", 200),
                             "nextStep": "", "hasFeatureDomain": item.id in used_features,
                             "status": task_status.get(item.id) or ("done" if latest and latest[0] == "assistant" else ("waiting" if latest else "idle"))}
    return {"state": board.state_json if board else BoardState().model_dump(), "previews": previews}


@router.put("")
def save_board(payload: BoardState, db: Db, context: CurrentContext):
    user_id = context[0].id
    valid_ids = set(db.scalars(select(Conversation.id).where(Conversation.user_id == user_id)).all())
    state = payload.model_dump()
    if "synapse" not in payload.model_fields_set:
        state.pop("synapse", None)
    if len(state["nodes"]) > 2000 or len(state["groups"]) > 200 or len(state["edges"]) > 5000:
        raise HTTPException(400, "会话地图过大")
    if not set(state["nodes"]).issubset(valid_ids):
        raise HTTPException(400, "地图包含不属于当前用户的会话")
    if any(edge.get("source") not in valid_ids or edge.get("target") not in valid_ids
           for edge in state["edges"]):
        raise HTTPException(400, "连线引用了无效会话")
    if len(json.dumps(state, ensure_ascii=False).encode()) > 1_500_000:
        raise HTTPException(400, "会话地图数据过大")
    board = db.get(ConversationMap, user_id)
    if board:
        board.state_json = state
        board.updated_at = utcnow()
    else:
        db.add(ConversationMap(user_id=user_id, state_json=state))
    db.commit()
    return {"ok": True}


@router.post("/{conversation_id}/digest")
def generate_digest(conversation_id: str, request: Request, db: Db, context: CurrentContext):
    item = owned(db, context[0].id, conversation_id)
    messages = source_messages(db, item.id)[-40:]
    fallback = digest_fallback(item, messages)
    if not messages:
        return fallback
    transcript = "\n".join(f"{'用户' if row.role == 'user' else '助手'}: {row.content[:1200]}" for row in messages)[-24000:]
    try:
        config = require_runtime_model("text", request.app.state.settings.model_config_path)
        response, _ = complete_text(config, [
            {"role": "system", "content": "你是会话整理助手。仅根据对话提取实际结论，不臆造。严格输出 JSON 对象，字段 summary（最多100字）、keyFindings（最多160字）、nextStep（最多80字；没有明确下一步就留空）。"},
            {"role": "user", "content": f"会话标题：{item.title}\n对话：\n{transcript}"},
        ])
        match = re.search(r"\{[\s\S]*\}", response)
        parsed = json.loads(match.group(0)) if match else {}
        return {"summary": clean_text(parsed.get("summary"), 200) or fallback["summary"],
                "keyFindings": clean_text(parsed.get("keyFindings"), 320),
                "nextStep": clean_text(parsed.get("nextStep"), 160)}
    except (RuntimeError, TextGenerationError, ValueError, TypeError):
        return fallback


def branch_context(db, user_id, source_id, mode):
    source = owned(db, user_id, source_id) if source_id else None
    if mode != "none" and not source:
        raise HTTPException(400, "继承上下文需要来源会话")
    inherited = ""
    if source and mode == "digest":
        board = db.get(ConversationMap, user_id)
        node = (board.state_json.get("nodes") or {}).get(source.id, {}) if board else {}
        digest = node.get("digest") or {}
        inherited = (f"来源会话《{source.title}》\n摘要：{clean_text(digest.get('summary'), 3000)}\n"
                     f"关键结论：{clean_text(digest.get('keyFindings'), 3000)}\n"
                     f"下一步：{clean_text(digest.get('nextStep'), 1000)}")
        if not digest.get("summary"):
            inherited = f"来源会话《{source.title}》\n摘要：{digest_fallback(source, source_messages(db, source.id))['summary']}"
    elif source and mode == "full":
        transcript = "\n".join(f"{'用户' if row.role == 'user' else '助手'}：{row.content}"
                               for row in source_messages(db, source.id))
        if len(transcript) > 58000:
            raise HTTPException(413, "来源会话过长，无法完整注入；请选择摘要注入")
        inherited = f"来源会话《{source.title}》完整对话（按时间顺序）：\n{transcript}"
    return inherited


@router.post("/branch-preview")
def preview_branch(payload: BranchPreviewRequest, db: Db, context: CurrentContext):
    return {"context": branch_context(db, context[0].id, payload.source_id, payload.mode)}


@router.post("/inject")
def inject_into_conversation(payload: InjectRequest, db: Db, context: CurrentContext):
    user_id = context[0].id
    if payload.source_id == payload.target_id:
        raise HTTPException(400, "不能将会话注入自身")
    owned(db, user_id, payload.source_id)
    owned(db, user_id, payload.target_id)
    board = db.get(ConversationMap, user_id)
    nodes = (board.state_json.get("nodes") or {}) if board else {}
    source_group = (nodes.get(payload.source_id) or {}).get("groupId")
    target_group = (nodes.get(payload.target_id) or {}).get("groupId")
    if source_group != target_group:
        raise HTTPException(400, "不同工作区的会话不能注入")
    inherited = branch_context(db, user_id, payload.source_id, payload.mode)
    if not inherited.strip():
        raise HTTPException(400, "来源会话没有可注入的内容")
    existing = db.get(ConversationInheritance, payload.target_id)
    if existing:
        if inherited in existing.context:
            return {"ok": True, "contextLength": len(existing.context)}
        combined = existing.context + "\n\n" + inherited
        if len(combined) > 60000:
            raise HTTPException(413, "目标会话的注入上下文已达到上限")
        existing.context = combined
        existing.mode = "mixed"
    else:
        if len(inherited) > 60000:
            raise HTTPException(413, "注入内容过长")
        existing = ConversationInheritance(conversation_id=payload.target_id, source_id=payload.source_id,
                                           mode=payload.mode, context=inherited)
        db.add(existing)
    db.commit()
    return {"ok": True, "contextLength": len(existing.context)}


@router.post("/branch", response_model=ConversationOut)
def create_branch(payload: BranchRequest, db: Db, context: CurrentContext):
    user_id = context[0].id
    source = owned(db, user_id, payload.source_id) if payload.source_id else None
    if payload.source_message_id:
        if not source or payload.mode != "full":
            raise HTTPException(400, "从指定轮次创建分支需要完整上下文")
        rows = source_messages(db, source.id)
        boundary = next((index for index, row in enumerate(rows) if row.id == payload.source_message_id and row.role == "assistant"), None)
        if boundary is None:
            raise HTTPException(404, "来源回复不存在")
        prior = db.get(ConversationInheritance, source.id)
        transcript = "\n".join(f"{'用户' if row.role == 'user' else '助手'}：{row.content}" for row in rows[:boundary + 1])
        inherited = "\n\n".join(filter(None, [prior.context if prior else "", f"来源会话《{source.title}》截至选中回复的对话：\n{transcript}"]))
        if len(inherited) > 60000:
            raise HTTPException(413, "来源分支上下文过长")
    else:
        inherited = branch_context(db, user_id, payload.source_id, payload.mode)
    if payload.context is not None and payload.mode != "none":
        inherited = payload.context.strip()
    item = Conversation(user_id=user_id, title=payload.title.strip(), task_id=payload.task_id)
    db.add(item)
    db.flush()
    if inherited:
        db.add(ConversationInheritance(conversation_id=item.id, source_id=source.id,
                                       mode=payload.mode, context=inherited))
    db.commit()
    return ConversationOut.from_record(item, 0)
