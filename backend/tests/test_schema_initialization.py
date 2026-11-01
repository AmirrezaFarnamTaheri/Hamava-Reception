"""Fresh-install database contracts; no earlier schema versions are supported."""
import pytest
from sqlalchemy import inspect, text

from receptionist.db import Base, make_engine
from receptionist.schema import initialize_schema, verify_schema


def test_empty_database_is_initialized_once_without_history_table(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    try:
        initialize_schema(engine)
        initialize_schema(engine)
        with engine.connect() as db:
            assert set(inspect(db).get_table_names()) == set(Base.metadata.tables)
            verify_schema(db)
            assert "schema_version" not in inspect(db).get_table_names()
    finally:
        engine.dispose()


def test_partial_database_is_rejected_without_creating_other_tables(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'partial.db'}")
    try:
        with engine.begin() as db:
            Base.metadata.tables["tenants"].create(db)
        with pytest.raises(RuntimeError, match="missing:"):
            initialize_schema(engine)
        with engine.connect() as db:
            assert inspect(db).get_table_names() == ["tenants"]
    finally:
        engine.dispose()


def test_historical_version_table_is_rejected_without_changes(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'obsolete.db'}")
    try:
        with engine.begin() as db:
            db.execute(text("CREATE TABLE schema_version (version VARCHAR(20) PRIMARY KEY)"))
        with pytest.raises(RuntimeError, match="unexpected:"):
            initialize_schema(engine)
        with engine.connect() as db:
            assert inspect(db).get_table_names() == ["schema_version"]
    finally:
        engine.dispose()


def test_missing_column_is_not_silently_repaired(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'drift.db'}")
    try:
        initialize_schema(engine)
        with engine.begin() as db:
            db.execute(text("ALTER TABLE users DROP COLUMN name"))
        with pytest.raises(RuntimeError, match="missing columns users: name"):
            initialize_schema(engine)
        with engine.connect() as db:
            with pytest.raises(RuntimeError, match="missing columns users: name"):
                verify_schema(db)
    finally:
        engine.dispose()


def test_failed_initial_validation_leaves_empty_sqlite_database(tmp_path, monkeypatch):
    import receptionist.schema as module

    engine = make_engine(f"sqlite:///{tmp_path / 'failed.db'}")
    try:
        def fail(_connection):
            raise RuntimeError("simulated schema verification failure")

        monkeypatch.setattr(module, "verify_schema", fail)
        with pytest.raises(RuntimeError, match="simulated"):
            initialize_schema(engine)
        with engine.connect() as db:
            assert inspect(db).get_table_names() == []
    finally:
        engine.dispose()
