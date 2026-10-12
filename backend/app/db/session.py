from sqlalchemy import create_engine, event

from app.core.config import Settings
from app.core.storage_layout import STATE_SCHEMA, state_database
from app.db.storage_migration import ensure_storage
from app.db import storage_integrity  # noqa: F401; transactional cross-store guards


def make_engine(settings: Settings):
    ensure_storage(settings)
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {})
    engine._mindpilot_storage_isolated = True
    if settings.database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA busy_timeout=10000")
            cursor.execute(f"ATTACH DATABASE ? AS {STATE_SCHEMA}", (str(state_database(settings)),))
            # Rollback journals allow one atomic commit across the two SQLite files.
            for schema in ("main", STATE_SCHEMA):
                cursor.execute(f"PRAGMA {schema}.journal_mode=DELETE")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine

