"""Database setup. SQLite is the local demo; PostgreSQL is the production target."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, UniqueConstraint, create_engine, event, inspect
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.types import TypeDecorator

from .config import settings


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("A timezone-aware timestamp is required")
            return value.astimezone(UTC)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return value


class Base(DeclarativeBase):
    pass


def validate_schema(connection, *, table_names=None) -> None:
    """Fail startup on a missing column or lost integrity constraint.

    This is a drift guard, not a replacement for a forward data migration. It
    never edits an existing schema or stamps an unrecognized legacy database.
    """
    inspector = inspect(connection)
    existing = set(inspector.get_table_names())
    problems = []
    for name, table in Base.metadata.tables.items():
        if table_names is not None and name not in table_names:
            continue
        if name not in existing:
            problems.append(f"missing table {name}")
            continue
        columns = {column["name"] for column in inspector.get_columns(name)}
        if missing := set(table.columns.keys()) - columns:
            problems.append(f"missing columns {name}: {','.join(sorted(missing))}")
        unique = {tuple(constraint["column_names"]) for constraint in inspector.get_unique_constraints(name)}
        for constraint in table.constraints:
            if isinstance(constraint, UniqueConstraint) and tuple(column.name for column in constraint.columns) not in unique:
                problems.append(f"missing unique constraint {name}:{constraint.name or ','.join(c.name for c in constraint.columns)}")
        actual_pk = set(inspector.get_pk_constraint(name).get("constrained_columns", []))
        if actual_pk != {column.name for column in table.primary_key.columns}:
            problems.append(f"primary key differs on {name}")
        actual_foreign_keys = {(tuple(item["constrained_columns"]), item["referred_table"], tuple(item["referred_columns"]))
                               for item in inspector.get_foreign_keys(name)}
        for constraint in table.foreign_key_constraints:
            expected = (tuple(column.name for column in constraint.columns), constraint.referred_table.name,
                        tuple(element.column.name for element in constraint.elements))
            if expected not in actual_foreign_keys:
                problems.append(f"foreign key differs on {name}")
    if problems:
        raise RuntimeError("Database schema does not match this release; apply an explicit migration: " + "; ".join(problems[:20]))


def now_utc() -> datetime:
    return datetime.now(UTC)


def make_engine(url: str):
    engine = create_engine(
        url, pool_pre_ping=True, connect_args={"check_same_thread": False, "timeout": 15} if url.startswith("sqlite") else {}
    )
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def configure_sqlite(connection, _record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=15000")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as db:
        try:
            yield db
        except Exception:
            db.rollback()
            raise
