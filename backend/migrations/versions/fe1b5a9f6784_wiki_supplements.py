"""Persist query-driven Wiki enrichment separately from compilation jobs."""
from app.db.migration_ops import op
from app.db.models import WikiSupplementJob

revision = 'fe1b5a9f6784'
down_revision = 'fd9a4f8e5673'
branch_labels = None
depends_on = None


def upgrade():
    WikiSupplementJob.__table__.create(op.get_bind())


def downgrade():
    WikiSupplementJob.__table__.drop(op.get_bind())
