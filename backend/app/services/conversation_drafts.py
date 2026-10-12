"""Reuse a user's unused default conversation and consolidate legacy duplicates."""
from copy import deepcopy

from sqlalchemy import or_, select

from app.db.models import AgentRun, AgentTask, Conversation, ConversationInheritance, ConversationMap, Message, User


def single_empty_conversation(db, user_id, *, create=False):
    # Serialize across tabs and workers before checking for an existing draft.
    if db.bind.dialect.name == 'sqlite':
        db.connection().exec_driver_sql('BEGIN IMMEDIATE')
    else:
        db.execute(select(User.id).where(User.id == user_id).with_for_update())
    rows = db.scalars(select(Conversation).where(
        Conversation.user_id == user_id,
        Conversation.title == '新会话', Conversation.task_id == 'general',
        ~select(Message.id).where(Message.conversation_id == Conversation.id).exists(),
        ~select(AgentRun.id).where(AgentRun.conversation_id == Conversation.id).exists(),
        ~select(AgentTask.id).where(AgentTask.conversation_id == Conversation.id).exists(),
        ~select(ConversationInheritance.conversation_id).where(or_(
            ConversationInheritance.conversation_id == Conversation.id,
            ConversationInheritance.source_id == Conversation.id)).exists(),
    ).order_by(Conversation.pinned.desc(), Conversation.updated_at.desc(), Conversation.id)).all()
    keep = rows[0] if rows else None
    removed = {item.id for item in rows[1:]}
    if removed:
        board = db.get(ConversationMap, user_id)
        if board:
            state = deepcopy(board.state_json)
            state['nodes'] = {key: value for key, value in state.get('nodes', {}).items() if key not in removed}
            state['edges'] = [edge for edge in state.get('edges', []) if edge.get('source') not in removed and edge.get('target') not in removed]
            board.state_json = state
        for item in rows[1:]:
            db.delete(item)
    if keep is None and create:
        keep = Conversation(user_id=user_id, title='新会话', task_id='general')
        db.add(keep)
    db.commit()
    return keep
