"""model configurations without secrets

Revision ID: a64e0a7bd211
Revises: ea56c3278700
"""
from app.db.migration_ops import op, reference
import sqlalchemy as sa

revision = "a64e0a7bd211"
down_revision = "ea56c3278700"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("model_configurations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("model", sa.String(160), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("image_input", sa.Boolean(), nullable=False),
        sa.Column("file_input", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "category", name="uq_model_config_user_category"))
    op.create_index("ix_model_configurations_user_id", "model_configurations", ["user_id"])


def downgrade():
    op.drop_index("ix_model_configurations_user_id", table_name="model_configurations")
    op.drop_table("model_configurations")
