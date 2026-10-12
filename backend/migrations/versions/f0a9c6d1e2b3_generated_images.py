"""Store local generated image metadata.

Revision ID: f0a9c6d1e2b3
Revises: a64e0a7bd211
"""

from app.db.migration_ops import op, reference
import sqlalchemy as sa


revision = "f0a9c6d1e2b3"
down_revision = "a64e0a7bd211"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "generated_images",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("size", sa.String(20), nullable=False),
        sa.Column("mode", sa.String(12), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_generated_images_user_id", "generated_images", ["user_id"])
    op.create_index("ix_generated_images_user_created", "generated_images", ["user_id", "created_at"])


def downgrade():
    op.drop_index("ix_generated_images_user_created", table_name="generated_images")
    op.drop_index("ix_generated_images_user_id", table_name="generated_images")
    op.drop_table("generated_images")
