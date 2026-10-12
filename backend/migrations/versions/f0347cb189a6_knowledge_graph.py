"""Personal graph indexes stay in the business database."""
from app.db.migration_ops import op
from app.db.models import KnowledgeGraphIndex

revision = 'f0347cb189a6'
down_revision = 'ff2c6ba07895'
branch_labels = None
depends_on = None


def upgrade():
    KnowledgeGraphIndex.__table__.create(op.get_bind())


def downgrade():
    KnowledgeGraphIndex.__table__.drop(op.get_bind())
