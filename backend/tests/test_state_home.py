from contextlib import closing
import sqlite3

import pytest

from app.core.state_home import prepare_state_home


def test_hidden_home_upgrade_keeps_business_database_out_of_state_home(tmp_path):
    data = tmp_path / "backend" / "data"
    data.mkdir(parents=True)
    legacy = tmp_path / "mindpoilt"
    (legacy / "locks").mkdir(parents=True)
    (legacy / "sessions").mkdir()
    (legacy / "sessions" / "history.jsonl").write_bytes(b"original-event\n")
    (legacy / "config.json").write_text("{}", encoding="utf-8")
    with closing(sqlite3.connect(data / "mindpilot.db")) as old:
        old.execute("PRAGMA journal_mode=WAL")
        old.execute("CREATE TABLE example (value TEXT)")
        old.execute("INSERT INTO example VALUES ('committed-in-wal')")
        old.commit()
        root, database = prepare_state_home(tmp_path, data)
        assert root == tmp_path / ".mindpoilt" and not legacy.exists()
        assert (root / "sessions/history.jsonl").read_bytes() == b"original-event\n"
        assert not (root / "locks").exists()
        for name in ("sessions", "archived_sessions", "memories", "thread-writer-locks", "tmp", "backups"):
            assert (root / name).is_dir()
        assert not database.exists()
        old.execute("INSERT INTO example VALUES ('old-state')")
        old.commit()
        prepare_state_home(tmp_path, data)
        assert not database.exists()
        assert old.execute("SELECT value FROM example").fetchall() == [("committed-in-wal",), ("old-state",)]
    assert not list((root / "tmp").iterdir())


def test_conflicting_state_homes_stop_without_touching_either(tmp_path):
    (tmp_path / "mindpoilt").mkdir()
    (tmp_path / ".mindpoilt").mkdir()
    with pytest.raises(RuntimeError, match="同时存在"):
        prepare_state_home(tmp_path, tmp_path / "data")
    assert (tmp_path / "mindpoilt").is_dir()
    assert (tmp_path / ".mindpoilt").is_dir()
