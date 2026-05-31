"""SQLAlchemy declarative base and shared model mixins.

Everything here is database-agnostic ORM scaffolding:
- `Base` is the parent class every model inherits from.
- The naming convention ensures every index/constraint gets a predictable,
  deterministic name. This matters because Alembic (Segment 3) generates
  migrations by diffing the models against the database — stable names mean
  stable, reproducible migrations instead of random auto-generated identifiers.
- The mixins add columns shared by every table (a UUID primary key and
  created/updated timestamps) without repeating them on each model.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Templates SQLAlchemy uses to name constraints/indexes.
# ix=index, uq=unique, ck=check, fk=foreign key, pk=primary key.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDMixin:
    """Adds a UUID primary key, generated application-side on insert."""

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    """Adds created_at / updated_at, both managed by the database."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
