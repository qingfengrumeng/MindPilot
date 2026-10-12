"""Store personal workbench sections in the application database.

Revision ID: f6b2c9d4e8a1
Revises: e62b41a90c35
"""

from app.db.migration_ops import op, reference
import sqlalchemy as sa

revision = "f6b2c9d4e8a1"
down_revision = "e62b41a90c35"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workbench_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("links", sa.JSON(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workbench_entries_user_id", "workbench_entries", ["user_id"])
    op.create_index("ix_workbench_entries_kind", "workbench_entries", ["kind"])
    op.create_index("ix_workbench_entries_user_kind_updated", "workbench_entries", ["user_id", "kind", "updated_at"])


def downgrade():
    op.drop_table("workbench_entries")
