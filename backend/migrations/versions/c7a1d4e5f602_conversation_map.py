"""Persist conversation map and branch context.

Revision ID: c7a1d4e5f602
Revises: f6b2c9d4e8a1
"""
from app.db.migration_ops import op, reference
import sqlalchemy as sa

revision = "c7a1d4e5f602"
down_revision = "f6b2c9d4e8a1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "conversation_maps",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "conversation_inheritance",
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey(reference("conversations.id"), ondelete="CASCADE"), primary_key=True),
        sa.Column("source_id", sa.String(36), sa.ForeignKey(reference("conversations.id"), ondelete="SET NULL")),
        sa.Column("mode", sa.String(12), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),
    )


def downgrade():
    op.drop_table("conversation_inheritance")
    op.drop_table("conversation_maps")
