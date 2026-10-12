"""Track vectorization progress for manually started document jobs.

Revision ID: c9d0e1f2a3b4
Revises: b7c8d9e0f1a2
"""

from app.db.migration_ops import op, reference
import sqlalchemy as sa


revision = "c9d0e1f2a3b4"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("documents", sa.Column("indexed_chunks", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("documents", "indexed_chunks")
