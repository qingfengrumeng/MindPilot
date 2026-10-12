"""Recoverable migration from the former combined database into two stores."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from app.core.state_home import checked_path, migration_lock
from app.core.storage_layout import BUSINESS_TABLES, STATE_SCHEMA, STATE_TABLES, state_database


def _tables(path):
    if not path.exists():
        return set()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        return {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def _digest(path):
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def _save_manifest(path, content):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(content, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _publish(manifest_path, manifest, business, state):
    # A pending manifest is durable before either replacement. A restart resumes
    # publication rather than treating a half-published pair as a new migration.
    for name, target in (("state", state), ("business", business)):
        item = manifest[name]
        expected = target.with_name(target.name + ".migration-" + manifest["id"])
        temporary = checked_path(item["temporary"])
        if temporary != expected or item["target"] != str(target):
            raise RuntimeError("Invalid storage migration paths")
        if temporary.exists():
            if _digest(temporary) != item["sha256"]:
                raise RuntimeError("Storage migration staging file failed verification")
            os.replace(temporary, target)
        elif not target.exists() or _digest(target) != item["sha256"]:
            raise RuntimeError("Storage migration is incomplete; restore the recorded backup")
    manifest_path.unlink()


def _upgrade_snapshot(path):
    from alembic import command
    from alembic.config import Config
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.attributes.update(database_url=f"sqlite:///{path.as_posix()}", split_storage=False)
    command.upgrade(config, "head")


def _relocate_combined_backups(state, business):
    old_backups = checked_path(state.parent / "backups")
    if not old_backups.exists():
        return
    for source in old_backups.iterdir():
        source = checked_path(source)
        if not source.is_file():
            continue
        with source.open("rb") as handle:
            if handle.read(16) != b"SQLite format 3\x00":
                continue
        if not (_tables(source) & BUSINESS_TABLES):
            continue
        destination_dir = checked_path(business.parent / "backups")
        destination_dir.mkdir(exist_ok=True)
        destination = checked_path(destination_dir / ("legacy-state-" + source.name))
        if destination.exists():
            raise RuntimeError("Legacy backup destination already exists; overwrite refused")
        # Validate both absolute paths before moving a file across the boundaries.
        if not source.is_relative_to(state.parent) or not destination.is_relative_to(business.parent):
            raise RuntimeError("Invalid backup migration path")
        source.rename(destination)


def _partition(source, business_stage, state_stage):
    from app.db.base import Base
    from app.db import models  # noqa: F401

    engine = create_engine(f"sqlite:///{business_stage.as_posix()}")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(f"ATTACH DATABASE ? AS {STATE_SCHEMA}", (str(state_stage),))
            Base.metadata.create_all(connection)
            connection.commit()
    finally:
        engine.dispose()
    with closing(sqlite3.connect(business_stage)) as db:
        db.execute(f"ATTACH DATABASE ? AS {STATE_SCHEMA}", (str(state_stage),))
        db.execute("ATTACH DATABASE ? AS legacy", (str(source),))
        db.execute("BEGIN IMMEDIATE")
        tables = _tables(source)
        unknown = tables - STATE_TABLES - BUSINESS_TABLES - {"alembic_version"}
        if unknown:
            raise RuntimeError("Unclassified legacy tables: " + ", ".join(sorted(unknown)))
        for name in sorted(tables - {"alembic_version"}):
            destination = STATE_SCHEMA if name in STATE_TABLES else "main"
            columns = [row[1] for row in db.execute(f'PRAGMA legacy.table_info("{name}")')]
            quoted = ", ".join('"' + column + '"' for column in columns)
            db.execute(f'INSERT INTO {destination}."{name}" ({quoted}) '
                       f'SELECT {quoted} FROM legacy."{name}"')
            before = db.execute(f'SELECT COUNT(*) FROM legacy."{name}"').fetchone()[0]
            after = db.execute(f'SELECT COUNT(*) FROM {destination}."{name}"').fetchone()[0]
            mismatch = db.execute(f'SELECT {quoted} FROM legacy."{name}" EXCEPT '
                                  f'SELECT {quoted} FROM {destination}."{name}" LIMIT 1').fetchone()
            if before != after or mismatch:
                raise RuntimeError(f"Storage migration verification failed: {name}")
        db.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        db.execute("INSERT INTO alembic_version SELECT * FROM legacy.alembic_version")
        for schema in ("main", STATE_SCHEMA):
            if db.execute(f"PRAGMA {schema}.integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Storage migration integrity check failed")
            if db.execute(f"PRAGMA {schema}.foreign_key_check").fetchall():
                raise RuntimeError("Storage migration foreign key check failed")
        # Cross-file foreign keys cannot be expressed in SQLite DDL. Validate
        # their existing rows too, before publishing either database.
        for table in Base.metadata.tables.values():
            for fk in table.foreign_keys:
                parent = fk.column.table
                if table.schema == parent.schema:
                    continue
                local_schema, parent_schema = table.schema or "main", parent.schema or "main"
                missing = db.execute(
                    f'SELECT 1 FROM {local_schema}."{table.name}" AS child '
                    f'LEFT JOIN {parent_schema}."{parent.name}" AS parent '
                    f'ON child."{fk.parent.name}" = parent."{fk.column.name}" '
                    f'WHERE child."{fk.parent.name}" IS NOT NULL '
                    f'AND parent."{fk.column.name}" IS NULL LIMIT 1').fetchone()
                if missing:
                    raise RuntimeError(f"Storage migration cross-store reference check failed: {table.name}")
        db.commit()


def ensure_storage(settings):
    url = make_url(settings.database_url)
    if url.get_backend_name() != "sqlite":
        raise RuntimeError("The local data layout requires SQLite")
    state = state_database(settings)
    state.parent.mkdir(parents=True, exist_ok=True)
    if not url.database or url.database == ":memory:":
        return
    business = checked_path(Path(url.database).resolve())
    if business == state:
        raise RuntimeError("Business and agent state databases must use different files")
    business.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = checked_path(business.with_name("." + business.name + ".storage-migration.json"))
    with migration_lock(state.parent):
        if manifest_path.exists():
            _publish(manifest_path, json.loads(manifest_path.read_text(encoding="utf-8")), business, state)
        state_tables, business_tables = _tables(state), _tables(business)
        mixed_state = bool(state_tables & BUSINESS_TABLES)
        mixed_business = bool(business_tables & STATE_TABLES)
        if mixed_state and business_tables:
            raise RuntimeError("Both databases contain existing data; automatic overwrite refused")
        if mixed_business and state_tables:
            raise RuntimeError("Both databases contain existing data; automatic overwrite refused")
        source = state if mixed_state else business if mixed_business else None
        old = checked_path(business.parent / "mindpilot.db")
        if source is None and not state_tables and not business_tables and old.is_file():
            source = old
        if source is None:
            _relocate_combined_backups(state, business)
            return
        migration_id = uuid.uuid4().hex
        backups = checked_path(business.parent / "backups")
        backups.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = checked_path(backups / f"combined-{stamp}-{migration_id}.sqlite")
        snapshot = checked_path(backups / f".migration-source-{migration_id}.sqlite")
        business_stage = business.with_name(business.name + ".migration-" + migration_id)
        state_stage = state.with_name(state.name + ".migration-" + migration_id)
        try:
            # Fail promptly if a writer is already active. Holding the reservation
            # prevents new writes while the snapshot is prepared and checked.
            with closing(sqlite3.connect(source, timeout=1)) as guard:
                guard.execute("PRAGMA journal_mode=DELETE")
                guard.execute("BEGIN IMMEDIATE")
                with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as reader:
                    with closing(sqlite3.connect(backup)) as destination:
                        reader.backup(destination)
                    with closing(sqlite3.connect(snapshot)) as destination:
                        reader.backup(destination)
                _upgrade_snapshot(snapshot)
                _partition(snapshot, business_stage, state_stage)
                manifest = {"format_version": 1, "id": migration_id, "backup": str(backup)}
                for name, target, temporary in (("business", business, business_stage),
                                                ("state", state, state_stage)):
                    with temporary.open("r+b") as handle:
                        os.fsync(handle.fileno())
                    manifest[name] = {"target": str(target), "temporary": str(temporary),
                                      "sha256": _digest(temporary)}
                _save_manifest(manifest_path, manifest)
                guard.rollback()
            _publish(manifest_path, manifest, business, state)
            _relocate_combined_backups(state, business)
        finally:
            snapshot.unlink(missing_ok=True)
            if not manifest_path.exists():
                business_stage.unlink(missing_ok=True)
                state_stage.unlink(missing_ok=True)
