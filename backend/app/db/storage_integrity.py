"""Application enforcement for references crossing the two SQLite files.

SQLite enforces foreign keys inside each file, but cannot declare one across an
ATTACH boundary. These checks run before commit in the same database transaction.
"""
from sqlalchemy import delete, event, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

def _isolated(db):
    return getattr(db.get_bind(), "_mindpilot_storage_isolated", False)


@event.listens_for(Session, "before_flush")
def prepare_cross_store_changes(db, _context, _instances):
    if not _isolated(db):
        return
    from app.db.models import (AgentArtifact, AgentTask, Conversation, ConversationMap,
                               MemoryDocument, ModelConfiguration, User)
    db.info["cross_store_pending"] = [obj for obj in (*db.new, *db.dirty)
                                      if any(fk.column.table.schema != obj.__table__.schema
                                             for fk in obj.__table__.foreign_keys)]
    users = {obj.id for obj in db.deleted if isinstance(obj, User)}
    conversations = {obj.id for obj in db.deleted if isinstance(obj, Conversation)}
    tasks = {obj.id for obj in db.deleted if isinstance(obj, AgentTask)}
    if users or conversations:
        conditions = []
        if users:
            conditions.append(AgentTask.user_id.in_(users))
        if conversations:
            conditions.append(AgentTask.conversation_id.in_(conversations))
        from sqlalchemy import or_
        tasks.update(db.scalars(select(AgentTask.id).where(or_(*conditions))))
    frontier = tasks.copy()
    while frontier:
        children = set(db.scalars(select(AgentTask.id).where(AgentTask.parent_task_id.in_(frontier)))) - tasks
        tasks.update(children)
        frontier = children
    if tasks:
        db.execute(delete(AgentArtifact).where(AgentArtifact.task_id.in_(tasks)))
    if users:
        for model in (AgentTask, ConversationMap, MemoryDocument, ModelConfiguration):
            db.execute(delete(model).where(model.user_id.in_(users)))


@event.listens_for(Session, "after_flush_postexec")
def check_cross_store_references(db, _context):
    if not _isolated(db):
        return
    for obj in db.info.pop("cross_store_pending", []):
        if inspect(obj).deleted:
            continue
        for fk in obj.__table__.foreign_keys:
            if fk.column.table.schema == obj.__table__.schema:
                continue
            value = getattr(obj, fk.parent.key)
            if value is not None and db.scalar(select(fk.column).where(fk.column == value)) is None:
                raise IntegrityError("Cross-store reference is missing", {}, None)


@event.listens_for(Session, "after_rollback")
def clear_pending(db):
    db.info.pop("cross_store_pending", None)
