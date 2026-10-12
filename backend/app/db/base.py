from sqlalchemy import Table
from sqlalchemy.orm import DeclarativeBase

from app.core.storage_layout import STATE_SCHEMA, STATE_TABLES


class Base(DeclarativeBase):
    @classmethod
    def __table_cls__(cls, name, metadata, *args, **kwargs):
        if name in STATE_TABLES:
            kwargs["schema"] = STATE_SCHEMA
        return Table(name, metadata, *args, **kwargs)
