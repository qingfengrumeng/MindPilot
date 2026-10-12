import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.security import utcnow
from app.db.base import Base


def new_id() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    username_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    avatar: Mapped[str] = mapped_column(Text, default="", nullable=False)
    research_field: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    default_domain: Mapped[str] = mapped_column(String(80), default="personal_learning", nullable=False)
    bio: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    sessions: Mapped[list["AuthSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    generated_images: Mapped[list["GeneratedImage"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    username_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvaluationWorkspace(Base):
    __tablename__ = "evaluation_workspaces"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    refresh_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    remember: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User] = relationship(back_populates="sessions")


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(160), default="新会话", nullable=False)
    task_id: Mapped[str] = mapped_column(String(80), default="general", nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    user: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")
    agent_runs: Mapped[list["AgentRun"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")
    __table_args__ = (Index("ix_conversations_user_updated", "user_id", "updated_at"),)


class ConversationMap(Base):
    __tablename__ = "conversation_maps"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    state_json: Mapped[dict] = mapped_column("state", JSON, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class ConversationInheritance(Base):
    __tablename__ = "conversation_inheritance"
    conversation_id: Mapped[str] = mapped_column(ForeignKey("agent_state.conversations.id", ondelete="CASCADE"), primary_key=True)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("agent_state.conversations.id", ondelete="SET NULL"))
    mode: Mapped[str] = mapped_column(String(12), nullable=False)
    context: Mapped[str] = mapped_column(Text, nullable=False)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("agent_state.conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("agent_state.conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    trace_json: Mapped[dict] = mapped_column("trace", JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    conversation: Mapped[Conversation] = relationship(back_populates="agent_runs")
    __table_args__ = (Index("ix_agent_runs_conversation_created", "conversation_id", "created_at"),)


class ConversationJournal(Base):
    """Location/import checkpoint; Message remains a searchable SQLite projection."""
    __tablename__ = "conversation_journals"
    conversation_id: Mapped[str] = mapped_column(ForeignKey("agent_state.conversations.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    relative_path: Mapped[str] = mapped_column(String(240), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class SessionEvent(Base):
    """Transactional outbox. Committed events survive a failed filesystem write."""
    __tablename__ = "session_events"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), default=new_id, unique=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (Index("ix_session_events_pending", "delivered", "seq"),)


class MemoryExtraction(Base):
    __tablename__ = "memory_extractions"
    conversation_id: Mapped[str] = mapped_column(ForeignKey("agent_state.conversations.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    revision: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MemoryDocument(Base):
    """Checkpoint for regenerating atomically written Markdown artifacts."""
    __tablename__ = "memory_documents"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    revision: Mapped[str] = mapped_column(String(64), nullable=False)
    entries_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AgentTask(Base):
    __tablename__ = "agent_tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("agent_state.conversations.id", ondelete="CASCADE"), index=True)
    parent_task_id: Mapped[str | None] = mapped_column(ForeignKey("agent_state.agent_tasks.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[str] = mapped_column(String(80), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False, index=True)
    inputs_json: Mapped[dict] = mapped_column("inputs", JSON, default=dict, nullable=False)
    constraints_json: Mapped[dict] = mapped_column("constraints", JSON, default=dict, nullable=False)
    result_json: Mapped[dict] = mapped_column("result", JSON, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    __table_args__ = (Index("ix_agent_tasks_user_created", "user_id", "created_at"),)


class AgentTaskEvent(Base):
    __tablename__ = "agent_task_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("agent_state.agent_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    detail_json: Mapped[dict] = mapped_column("detail", JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AgentArtifact(Base):
    __tablename__ = "agent_artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("agent_state.agent_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    filename: Mapped[str] = mapped_column(String(180), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    source_ids_json: Mapped[list] = mapped_column("source_ids", JSON, default=list, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ModelConfiguration(Base):
    __tablename__ = "model_configurations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    model: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    image_input: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    file_input: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("user_id", "category", name="uq_model_config_user_category"),)


class GeneratedImage(Base):
    __tablename__ = "generated_images"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[str] = mapped_column(String(20), nullable=False)
    mode: Mapped[str] = mapped_column(String(12), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    user: Mapped[User] = relationship(back_populates="generated_images")
    __table_args__ = (Index("ix_generated_images_user_created", "user_id", "created_at"),)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream", nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    domain: Mapped[str] = mapped_column(String(80), default="personal_learning", nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pages: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    indexed_chunks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chunk_size: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="ready", nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    __table_args__ = (Index("ix_documents_user_created", "user_id", "created_at"),)


class DocumentWikiCompilation(Base):
    __tablename__='document_wiki_compilations'
    document_id:Mapped[str]=mapped_column(ForeignKey('documents.id',ondelete='CASCADE'),primary_key=True)
    user_id:Mapped[str]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),nullable=False,index=True)
    status:Mapped[str]=mapped_column(String(24),default='queued',nullable=False)
    completed_batches:Mapped[int]=mapped_column(Integer,default=0,nullable=False)
    total_batches:Mapped[int]=mapped_column(Integer,default=0,nullable=False)
    error_message:Mapped[str]=mapped_column(Text,default='',nullable=False)
    markdown:Mapped[str]=mapped_column(Text,default='',nullable=False)
    data_json:Mapped[dict]=mapped_column(JSON,default=dict,nullable=False)
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,onupdate=utcnow,nullable=False)


class WikiSupplementJob(Base):
    __tablename__ = 'wiki_supplement_jobs'
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id', ondelete='CASCADE'), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), default='queued', nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    wiki_context: Mapped[str] = mapped_column(Text, default='', nullable=False)
    evidence_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default='', nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class KnowledgeGraphIndex(Base):
    __tablename__ = 'knowledge_graph_indexes'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    status: Mapped[str] = mapped_column(String(24), default='empty', nullable=False)
    stage: Mapped[str] = mapped_column(Text, default='', nullable=False)
    completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default='', nullable=False)
    rebuild_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    data_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    chroma_id: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    document: Mapped[Document] = relationship(back_populates="chunks")
    __table_args__ = (Index("ix_document_chunks_document_order", "document_id", "chunk_index"),)


class WorkbenchEntry(Base):
    """User-owned workbench content. The database replaces the reference Vault."""

    __tablename__ = "workbench_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    tags_json: Mapped[list] = mapped_column("tags", JSON, default=list, nullable=False)
    links_json: Mapped[list] = mapped_column("links", JSON, default=list, nullable=False)
    data_json: Mapped[dict] = mapped_column("data", JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    __table_args__ = (Index("ix_workbench_entries_user_kind_updated", "user_id", "kind", "updated_at"),)


class ConversationTitleJob(Base):
    """A permanent first-turn snapshot doubles as the once-only trigger marker."""
    __tablename__ = "conversation_title_jobs"
    conversation_id: Mapped[str] = mapped_column(ForeignKey("agent_state.conversations.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False, index=True)
    first_turn_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    expected_title: Mapped[str] = mapped_column(String(160), nullable=False)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
