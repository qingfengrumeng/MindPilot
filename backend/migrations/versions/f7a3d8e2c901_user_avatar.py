"""Persist personal profile avatars."""
from app.db.migration_ops import op, reference
import sqlalchemy as sa

revision = "f7a3d8e2c901"
down_revision = "c7a1d4e5f602"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("avatar", sa.Text(), nullable=False, server_default=""))


def downgrade():
    op.drop_column("users", "avatar")
