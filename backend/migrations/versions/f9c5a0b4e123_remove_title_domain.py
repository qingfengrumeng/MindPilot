"""Remove implicit title jobs and restore generated titles to the first query."""
import json
from app.db.migration_ops import op, reference
import sqlalchemy as sa
revision = "f9c5a0b4e123"
down_revision = "f8b4e9a3d012"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT conversation_id, result_json FROM conversation_title_jobs WHERE status = 'completed'"))
    for cid, raw in rows.fetchall():
        result = json.loads(raw) if isinstance(raw, str) else raw
        generated = (result or {}).get("title")
        first = connection.execute(sa.text("SELECT content FROM messages WHERE conversation_id = :id AND role = 'user' ORDER BY created_at, id LIMIT 1"), {"id": cid}).scalar()
        if generated and first and first.strip():
            connection.execute(sa.text("UPDATE conversations SET title = :title WHERE id = :id AND title = :generated"),
                               {"id": cid, "title": first.strip()[:160], "generated": generated})
    op.drop_table("conversation_title_jobs")


def downgrade():
    op.create_table("conversation_title_jobs",
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey(reference("conversations.id"), ondelete="CASCADE"), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("revision", sa.String(64), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_conversation_title_jobs_status", "conversation_title_jobs", ["status"])
