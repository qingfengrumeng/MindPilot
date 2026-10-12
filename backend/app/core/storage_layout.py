"""Explicit physical boundaries between agent state and application data."""
from pathlib import Path

from sqlalchemy.engine import make_url

from app.core.state_home import checked_path


STATE_SCHEMA = "agent_state"
STATE_TABLES = frozenset({
    "conversations", "conversation_maps", "conversation_inheritance", "messages",
    "agent_runs", "agent_tasks", "agent_task_events", "conversation_title_jobs",
    "conversation_journals", "session_events", "memory_extractions",
    "memory_documents", "model_configurations",
})
BUSINESS_TABLES = frozenset({
    "users", "login_attempts", "auth_sessions", "documents", "document_chunks",
    "agent_artifacts", "generated_images", "workbench_entries", "evaluation_workspaces", "document_wiki_compilations", "wiki_supplement_jobs", "knowledge_graph_indexes",
})


def state_root(settings):
    if settings.state_dir is not None:
        root = Path(settings.state_dir)
    else:
        database = make_url(settings.database_url).database
        root = (Path(database).resolve().parent / ".mindpoilt"
                if database and database != ":memory:"
                else settings.data_dir / ".mindpoilt")
    return checked_path(root).resolve()


def state_database(settings):
    return checked_path(state_root(settings) / "state_1.sqlite")


def business_directory(settings, *parts):
    root = checked_path(settings.data_dir).resolve()
    target = checked_path(root.joinpath(*parts)).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Business storage path escapes the data directory")
    target.mkdir(parents=True, exist_ok=True)
    return target


def prepare_business_directories(settings):
    for parts in (("documents",), ("chat_previews",), ("agent_artifacts",),
                  ("generated_images",), ("speech_cache", "asr"),
                  ("speech_cache", "tts"), ("model_comparisons",), ("backups",)):
        business_directory(settings, *parts)
