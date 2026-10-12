from contextlib import closing
from datetime import timedelta
from pathlib import Path
import sqlite3

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.security import utcnow
from app.core.storage_layout import BUSINESS_TABLES, STATE_TABLES, business_directory
from app.db.base import Base
from app.db.models import (AgentArtifact, AgentTask, AuthSession, Conversation, Document,
                           Message, User)
from app.db.session import make_engine
from app.db.storage_migration import ensure_storage
from app.services.session_journal import SessionJournal


def settings_for(root):
    return Settings(database_url=f"sqlite:///{(root / 'data' / 'mindpoilt.sqlite').as_posix()}",
                    jwt_secret="test-signing-secret-longer-than-thirty-two-bytes",
                    allowed_origins=(), data_dir=root / "data", state_dir=root / ".mindpoilt",
                    model_config_path=root / ".mindpoilt" / "models.json")


def tables(path):
    with closing(sqlite3.connect(path)) as db:
        return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def make_legacy(settings, *, business=False, revision="fc8f3e7d4562"):
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    path = settings.data_dir / "mindpilot.db" if business else settings.state_dir / "state_1.sqlite"
    engine = create_engine(f"sqlite:///{path.as_posix()}",
                           execution_options={"schema_translate_map": {"agent_state": None}})
    if revision == "fc8f3e7d4562":
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE alembic_version(version_num VARCHAR(32) PRIMARY KEY)")
            connection.exec_driver_sql("INSERT INTO alembic_version VALUES (?)", (revision,))
    else:
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        config.attributes.update(database_url=f"sqlite:///{path.as_posix()}", split_storage=False)
        command.upgrade(config, revision)
    with sessionmaker(engine)() as db:
        db.add(User(id="alice", username="alice", username_key="alice", display_name="Alice",
                    password_hash="preserved-password-hash"))
        db.add(AuthSession(id="login", user_id="alice", refresh_hash="f" * 64, remember=True,
                           expires_at=utcnow() + timedelta(days=30)))
        db.add(Conversation(id="chat", user_id="alice", title="Preserved conversation"))
        db.add(Message(id="query", conversation_id="chat", role="user", content="Preserved query"))
        db.add(Document(id="upload", user_id="alice", title="File", filename="file.txt",
                        storage_path=str(settings.data_dir / "documents" / "file.txt")))
        db.commit()
    engine.dispose()
    return path


def test_fresh_database_schema_is_physically_separated(tmp_path):
    settings = settings_for(tmp_path)
    engine = make_engine(settings)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with engine.connect() as connection:
        config.attributes.update(database_url=settings.database_url, connection=connection)
        command.upgrade(config, "head")
        for schema in ("main", "agent_state"):
            assert not connection.exec_driver_sql(f"PRAGMA {schema}.foreign_key_check").all()
    assert tables(settings.data_dir / "mindpoilt.sqlite") == BUSINESS_TABLES | {"alembic_version"}
    assert tables(settings.state_dir / "state_1.sqlite") == STATE_TABLES
    engine.dispose()


@pytest.mark.parametrize("business", [False, True])
def test_migrate_accounts_sessions_documents_and_context_without_changing_values(tmp_path, business):
    settings = settings_for(tmp_path)
    source = make_legacy(settings, business=business)
    with closing(sqlite3.connect(source)) as db:
        expected = {name: db.execute(f'SELECT * FROM "{name}"').fetchall()
                    for name in BUSINESS_TABLES | STATE_TABLES}
    ensure_storage(settings)
    for path, names in ((settings.data_dir / "mindpoilt.sqlite", BUSINESS_TABLES),
                        (settings.state_dir / "state_1.sqlite", STATE_TABLES)):
        with closing(sqlite3.connect(path)) as db:
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            for name in names:
                assert db.execute(f'SELECT * FROM "{name}"').fetchall() == expected[name]
    backups = list((settings.data_dir / "backups").glob("combined-*.sqlite"))
    assert len(backups) == 1 and "users" in tables(backups[0])
    ensure_storage(settings)
    assert list((settings.data_dir / "backups").glob("combined-*.sqlite")) == backups


def test_interrupted_publication_resumes_on_restart(tmp_path, monkeypatch):
    from app.db import storage_migration as migration
    settings = settings_for(tmp_path)
    make_legacy(settings)
    original = migration.os.replace
    business = settings.data_dir / "mindpoilt.sqlite"
    def fail_business(source, destination):
        if Path(destination) == business:
            raise OSError("simulated interrupted publication")
        return original(source, destination)
    with monkeypatch.context() as patch:
        patch.setattr(migration.os, "replace", fail_business)
        with pytest.raises(OSError, match="interrupted"):
            ensure_storage(settings)
    assert "users" not in tables(settings.state_dir / "state_1.sqlite")
    assert list(settings.data_dir.glob("*.storage-migration.json"))
    ensure_storage(settings)
    assert "users" in tables(business)
    assert not list(settings.data_dir.glob("*.storage-migration.json"))


def test_conflicting_existing_databases_are_not_overwritten(tmp_path):
    settings = settings_for(tmp_path)
    source = make_legacy(settings)
    business = settings.data_dir / "mindpoilt.sqlite"
    with closing(sqlite3.connect(business)) as db:
        db.execute("CREATE TABLE marker(value TEXT)")
        db.execute("INSERT INTO marker VALUES ('keep')")
        db.commit()
    before = source.read_bytes(), business.read_bytes()
    with pytest.raises(RuntimeError, match="overwrite refused"):
        ensure_storage(settings)
    assert before == (source.read_bytes(), business.read_bytes())


def test_legacy_mixed_backups_move_to_business_directory(tmp_path):
    settings = settings_for(tmp_path)
    source = make_legacy(settings)
    old = settings.state_dir / "backups"
    old.mkdir()
    backup = old / "old.sqlite"
    backup.write_bytes(source.read_bytes())
    ensure_storage(settings)
    assert not backup.exists()
    assert "users" in tables(settings.data_dir / "backups" / "legacy-state-old.sqlite")


def test_older_combined_schema_is_upgraded_before_partition(tmp_path):
    settings = settings_for(tmp_path)
    make_legacy(settings, revision="fa6d1c5b2340")
    engine = make_engine(settings)
    with sessionmaker(engine)() as db:
        assert db.get(Message, "query").content == "Preserved query"
        assert db.get(User, "alice").password_hash == "preserved-password-hash"
    assert "memory_documents" in tables(settings.state_dir / "state_1.sqlite")
    engine.dispose()


def test_unknown_legacy_tables_stop_migration_without_losing_source(tmp_path):
    settings = settings_for(tmp_path)
    source = make_legacy(settings)
    with closing(sqlite3.connect(source)) as db:
        db.execute("CREATE TABLE unclassified(value TEXT)")
        db.execute("INSERT INTO unclassified VALUES ('preserve')")
        db.commit()
    original = source.read_bytes()
    with pytest.raises(RuntimeError, match="Unclassified legacy tables"):
        ensure_storage(settings)
    assert source.read_bytes() == original
    assert not (settings.data_dir / "mindpoilt.sqlite").exists()


def test_existing_login_remains_valid_after_migration_and_service_restart(tmp_path):
    from fastapi.testclient import TestClient
    from app.core.security import create_access_token, hash_refresh_token
    from app.main import create_app
    settings = settings_for(tmp_path)
    source = make_legacy(settings)
    refresh = "pre-migration-refresh-cookie"
    with closing(sqlite3.connect(source)) as db:
        db.execute("UPDATE auth_sessions SET refresh_hash = ? WHERE id = 'login'", (hash_refresh_token(refresh),))
        db.commit()
    access = create_access_token("alice", "login", settings)
    auth = {"Authorization": f"Bearer {access}"}
    for _ in range(2):
        with TestClient(create_app(settings)) as client:
            assert client.get("/api/v1/auth/me", headers=auth).json()["username"] == "alice"
            client.cookies.set("mindpilot_refresh", refresh, domain="testserver.local", path="/api/v1/auth")
            response = client.post("/api/v1/auth/refresh")
            assert response.status_code == 200
            refresh = response.cookies.get("mindpilot_refresh")
            access = response.json()["accessToken"]
            auth = {"Authorization": f"Bearer {access}"}
            messages = client.get("/api/v1/conversations/chat/messages", headers=auth)
            assert messages.status_code == 200
            assert "Preserved query" in messages.text
            assert client.get("/api/v1/auth/me/statistics", headers=auth).status_code == 200


def test_account_and_outbox_updates_roll_back_together_and_cross_store_references_are_checked(tmp_path):
    settings = settings_for(tmp_path)
    engine = make_engine(settings)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    journal = SessionJournal(settings, factory)
    journal.install()
    with factory() as db:
        db.add(User(id="alice", username="alice", username_key="alice", display_name="Alice", password_hash="hash"))
        db.add(Conversation(id="chat", user_id="alice"))
        db.commit()
        db.get(User, "alice").display_name = "Rolled back"
        db.add(Message(conversation_id="chat", role="user", content="Rolled back"))
        db.flush()
        db.rollback()
        assert db.get(User, "alice").display_name == "Alice"
        assert not list(db.scalars(select(Message)))
        assert not journal.messages("alice", "chat")
        db.add(Conversation(user_id="missing-user"))
        with pytest.raises(IntegrityError, match="Cross-store"):
            db.commit()
        db.rollback()
    engine.dispose()


def test_deleting_a_conversation_cleans_artifact_metadata_in_business_database(tmp_path):
    settings = settings_for(tmp_path)
    engine = make_engine(settings)
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as db:
        db.add(User(id="alice", username="alice", username_key="alice", display_name="Alice", password_hash="hash"))
        db.flush()
        db.add(Conversation(id="chat", user_id="alice"))
        db.flush()
        db.add(AgentTask(id="task", user_id="alice", conversation_id="chat", agent_id="test", goal="test"))
        db.flush()
        db.add(AgentArtifact(id="artifact", user_id="alice", task_id="task", kind="text", filename="file.txt",
                             mime_type="text/plain", storage_path="file.txt"))
        db.commit()
        db.delete(db.get(Conversation, "chat"))
        db.commit()
        assert db.get(AgentArtifact, "artifact") is None
        assert db.get(AgentTask, "task") is None
    engine.dispose()


def test_reserved_speech_and_comparison_directories_stay_under_business_data(tmp_path):
    from app.core.storage_layout import prepare_business_directories
    settings = settings_for(tmp_path)
    prepare_business_directories(settings)
    assert (settings.data_dir / "speech_cache" / "asr").is_dir()
    assert (settings.data_dir / "speech_cache" / "tts").is_dir()
    assert (settings.data_dir / "model_comparisons").is_dir()
    with pytest.raises(ValueError, match="escapes"):
        business_directory(settings, "..", ".mindpoilt")
