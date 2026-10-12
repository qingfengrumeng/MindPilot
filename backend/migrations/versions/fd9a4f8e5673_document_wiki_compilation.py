"""Document Wiki compilation state belongs to the business database."""
from app.db.migration_ops import op
from app.db.models import DocumentWikiCompilation
revision='fd9a4f8e5673'
down_revision='fc8f3e7d4562'
branch_labels=None
depends_on=None
def upgrade():DocumentWikiCompilation.__table__.create(op.get_bind())
def downgrade():DocumentWikiCompilation.__table__.drop(op.get_bind())
