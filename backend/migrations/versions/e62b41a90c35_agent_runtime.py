"""Persist agent tasks, execution events and referenced artifacts.

Revision ID: e62b41a90c35
Revises: d4e5f6a7b8c9
"""

from app.db.migration_ops import op, reference
import sqlalchemy as sa


revision = "e62b41a90c35"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey(reference("conversations.id"), ondelete="CASCADE")),
        sa.Column("parent_task_id", sa.String(36), sa.ForeignKey(reference("agent_tasks.id"), ondelete="CASCADE")),
        sa.Column("agent_id", sa.String(80), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("constraints", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name, columns in (
        ("ix_agent_tasks_user_id", ["user_id"]),
        ("ix_agent_tasks_conversation_id", ["conversation_id"]),
        ("ix_agent_tasks_parent_task_id", ["parent_task_id"]),
        ("ix_agent_tasks_status", ["status"]),
        ("ix_agent_tasks_user_created", ["user_id", "created_at"]),
    ):
        op.create_index(name, "agent_tasks", columns)
    op.create_table(
        "agent_task_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey(reference("agent_tasks.id"), ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_task_events_task_id", "agent_task_events", ["task_id"])
    op.create_table(
        "agent_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.String(36), sa.ForeignKey(reference("agent_tasks.id"), ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("filename", sa.String(180), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_artifacts_user_id", "agent_artifacts", ["user_id"])
    op.create_index("ix_agent_artifacts_task_id", "agent_artifacts", ["task_id"])


def downgrade():
    op.drop_table("agent_artifacts")
    op.drop_table("agent_task_events")
    op.drop_table("agent_tasks")
