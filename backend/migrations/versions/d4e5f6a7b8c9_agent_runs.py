"""Persist per-turn agent monitor traces.

Revision ID: d4e5f6a7b8c9
Revises: c9d0e1f2a3b4
"""

from app.db.migration_ops import op, reference
import sqlalchemy as sa


revision = "d4e5f6a7b8c9"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey(reference("conversations.id"), ondelete="CASCADE"), nullable=False),
        sa.Column("trace", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_runs_conversation_id", "agent_runs", ["conversation_id"])
    op.create_index("ix_agent_runs_conversation_created", "agent_runs", ["conversation_id", "created_at"])


def downgrade():
    op.drop_index("ix_agent_runs_conversation_created", table_name="agent_runs")
    op.drop_index("ix_agent_runs_conversation_id", table_name="agent_runs")
    op.drop_table("agent_runs")
