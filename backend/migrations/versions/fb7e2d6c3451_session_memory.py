"""Session journal outbox and memory processing checkpoints."""
from app.db.migration_ops import op, reference
from app.db.models import ConversationJournal, SessionEvent, MemoryExtraction, MemoryDocument

revision = "fb7e2d6c3451"
down_revision = "fa6d1c5b2340"
branch_labels = None
depends_on = None


def upgrade():
    for model in (ConversationJournal, SessionEvent, MemoryExtraction, MemoryDocument):
        model.__table__.create(op.get_bind())


def downgrade():
    for model in (MemoryDocument, MemoryExtraction, SessionEvent, ConversationJournal):
        model.__table__.drop(op.get_bind())
