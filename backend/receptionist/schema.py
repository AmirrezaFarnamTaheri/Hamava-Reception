"""Creation and validation of the current schema; no historical upgrade paths."""
from sqlalchemy import inspect, text

from . import model_registry  # noqa: F401 -- register all mapped tables
from .db import Base, validate_schema


def verify_schema(connection) -> None:
    """Reject incomplete, unfamiliar and structurally incompatible databases."""
    existing = set(inspect(connection).get_table_names())
    expected = set(Base.metadata.tables)
    if existing != expected:
        missing = ", ".join(sorted(expected - existing)) or "none"
        extra = ", ".join(sorted(existing - expected)) or "none"
        raise RuntimeError(f"Database tables do not match current models (missing: {missing}; unexpected: {extra})")
    validate_schema(connection)


def initialize_schema(engine) -> None:
    """Create every mapped table only in an empty database; otherwise verify.

    The explicit SQLite transaction and PostgreSQL advisory lock serialize
    concurrent first starts. Existing tables are never rewritten or upgraded.
    """
    with engine.connect() as connection:
        try:
            if connection.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            elif connection.dialect.name == "postgresql":
                connection.execute(text("SELECT pg_advisory_xact_lock(47382915)"))
            if inspect(connection).get_table_names():
                verify_schema(connection)
            else:
                Base.metadata.create_all(connection, checkfirst=False)
                verify_schema(connection)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
