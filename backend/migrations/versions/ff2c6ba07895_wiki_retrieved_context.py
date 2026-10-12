"""Upgrade existing supplement queues with the other retrieved Wiki context."""
import sqlalchemy as sa
from app.db.migration_ops import op

revision = 'ff2c6ba07895'
down_revision = 'fe1b5a9f6784'
branch_labels = None
depends_on = None


def upgrade():
    columns = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('wiki_supplement_jobs')}
    if 'wiki_context' not in columns:
        op.add_column('wiki_supplement_jobs', sa.Column('wiki_context', sa.Text(), nullable=False, server_default=''))


def downgrade():
    op.drop_column('wiki_supplement_jobs', 'wiki_context')
