"""Temporary evaluation datasets belong to the business database."""
from app.db.migration_ops import op
from app.db.models import EvaluationWorkspace

revision = "fc8f3e7d4562"
down_revision = "fb7e2d6c3451"
branch_labels = None
depends_on = None


def upgrade():
    EvaluationWorkspace.__table__.create(op.get_bind())


def downgrade():
    EvaluationWorkspace.__table__.drop(op.get_bind())
