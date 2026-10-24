"""Exercise the retention contract on the production SQL dialect.

TEST_DATABASE_URL must identify an isolated PostgreSQL test service. Each case
creates and removes only its own random schema; no existing rows are inspected.
The same behavioral cases also run against the ordinary SQLite test fixture.
"""
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from receptionist import model_registry  # noqa: F401
from receptionist.db import Base
from receptionist.seed import seed_demo
import test_runtime_retention_v2 as retention


DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL.startswith("postgresql"),
    reason="Requires an explicitly configured isolated PostgreSQL test database",
)


@pytest.mark.parametrize("case", [
    retention.test_effective_limit_is_strictest_processing_tenant_and_original_pin,
    retention.test_real_worker_purges_shorter_original_and_published_limits_with_backup_evidence,
    retention.test_due_query_does_not_starve_short_pin_and_disabled_clinic_still_purges,
    retention.test_per_tenant_cap_does_not_starve_later_clinics,
], ids=lambda case: case.__name__.removeprefix("test_"))
def test_postgres_runtime_retention(case):
    schema = "hamava_controls_" + uuid4().hex
    admin = create_engine(DATABASE_URL, pool_pre_ping=True)
    engine = None
    with admin.begin() as connection:
        connection.execute(CreateSchema(schema))
    try:
        engine = create_engine(
            DATABASE_URL,
            pool_pre_ping=True,
            connect_args={"options": f"-csearch_path={schema} -ctimezone=UTC"},
        )
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with factory() as db:
            seed_demo(db)
        case(factory)
    finally:
        if engine is not None:
            engine.dispose()
        with admin.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        admin.dispose()
