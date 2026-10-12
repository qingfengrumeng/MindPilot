"""Durable background conversation titles."""
from app.db.migration_ops import op, reference
import sqlalchemy as sa
revision = "f8b4e9a3d012"
down_revision = "f7a3d8e2c901"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("conversation_title_jobs",
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey(reference("conversations.id"), ondelete="CASCADE"), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("revision", sa.String(64), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_conversation_title_jobs_status", "conversation_title_jobs", ["status"])


def downgrade():
    op.drop_table("conversation_title_jobs")
