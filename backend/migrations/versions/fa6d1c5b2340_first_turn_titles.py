"""Once-only first-turn title tasks."""
from app.db.migration_ops import op, reference
import sqlalchemy as sa
revision = "fa6d1c5b2340"
down_revision = "f9c5a0b4e123"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("conversation_title_jobs",
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey(reference("conversations.id"), ondelete="CASCADE"), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("first_turn_json", sa.JSON(), nullable=False),
        sa.Column("expected_title", sa.String(160), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_conversation_title_jobs_status", "conversation_title_jobs", ["status"])


def downgrade():
    op.drop_table("conversation_title_jobs")
