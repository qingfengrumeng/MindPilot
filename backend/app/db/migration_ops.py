"""Route historical Alembic operations to the same stores as ORM models."""
from alembic import op as original

from app.core.storage_layout import STATE_SCHEMA, STATE_TABLES


def split_storage():
    return original.get_context().config.attributes.get("split_storage", True)


def reference(target):
    table = target.split(".")[0]
    return f"{STATE_SCHEMA}.{target}" if split_storage() and table in STATE_TABLES else target


class StorageOperations:
    def __getattr__(self, name):
        action = getattr(original, name)
        if name == "get_bind":
            def get_bind():
                connection = action()
                return connection if split_storage() else connection.execution_options(
                    schema_translate_map={STATE_SCHEMA: None})
            return get_bind
        if name not in {"create_table", "drop_table", "add_column", "drop_column",
                        "create_index", "drop_index", "batch_alter_table"}:
            return action

        def routed(*args, **kwargs):
            table = (args[1] if name == "create_index" else kwargs.get("table_name")
                     if name == "drop_index" else args[0])
            if split_storage() and table in STATE_TABLES:
                kwargs.setdefault("schema", STATE_SCHEMA)
            return action(*args, **kwargs)
        return routed


op = StorageOperations()
