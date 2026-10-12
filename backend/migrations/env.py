from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import load_settings
from app.db.base import Base
from app.db import models  # noqa: F401


config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
database_url = config.attributes.get("database_url") or load_settings().database_url


def run_migrations_offline():
    context.configure(url=database_url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    provided = config.attributes.get("connection")
    if provided is not None:
        migrate(provided)
        return
    if config.attributes.get("split_storage", True):
        from dataclasses import replace
        from app.db.session import make_engine
        engine = make_engine(replace(load_settings(), database_url=database_url))
    else:
        engine = create_engine(database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        migrate(connection)
    engine.dispose()


def migrate(connection):
    if database_url.startswith("sqlite"):
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
    context.configure(connection=connection, target_metadata=target_metadata,
                      compare_type=True, include_schemas=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
