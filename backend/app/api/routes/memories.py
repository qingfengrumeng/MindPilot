"""Authenticated status and explicit background regeneration controls."""
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from sqlalchemy import select

from app.api.deps import CurrentContext, Db
from app.core.model_runtime import require_runtime_model
from app.db.models import MemoryDocument, MemoryExtraction

router = APIRouter(prefix="/memories", tags=["memories"])


@router.get("")
def memory_status(request: Request, db: Db, context: CurrentContext):
    user_id = context[0].id
    policy = request.app.state.session_journal.files.policy()
    document = db.get(MemoryDocument, user_id)
    jobs = db.scalars(select(MemoryExtraction).where(MemoryExtraction.user_id == user_id)).all()
    return {"enabled": policy.long_term_memory_enabled, "recentTurns": policy.recent_turns,
        "autoCompactTokenLimit": policy.auto_compact_token_limit,
        "contextWindowTokens": policy.context_window_tokens, "minimumIdleHours": policy.memory_min_idle_hours,
        "entries": len(document.entries_json) if document else 0,
        "updatedAt": document.updated_at if document else None,
        "jobs": [{"conversationId": job.conversation_id, "status": job.status,
                  "updatedAt": job.updated_at} for job in jobs]}


@router.post("/generate", status_code=202)
def generate_memories(request: Request, tasks: BackgroundTasks, context: CurrentContext):
    if not request.app.state.session_journal.files.policy().long_term_memory_enabled:
        raise HTTPException(409, "长期记忆已关闭")
    try:
        require_runtime_model("text", request.app.state.settings.model_config_path)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from None
    tasks.add_task(request.app.state.memories.run_pass, context[0].id, force=True)
    return {"status": "queued"}
