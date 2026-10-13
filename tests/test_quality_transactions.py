import os
import uuid

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from pharma_suite.db import create_db
from pharma_suite.quality.demo import make_bundle
from pharma_suite.quality.schema import audit, datasets, issues, records, runs
from pharma_suite.quality.store import approve, stage, validate_dataset
from pharma_suite.schema import tables


@pytest.fixture(params=["sqlite", "postgres"])
def quality_engine(request, tmp_path):
    if request.param == "sqlite":
        yield create_db(f"sqlite:///{tmp_path}/quality.db")
        return
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL required for PostgreSQL quality transaction tests")
    if not url.startswith("postgresql"):
        pytest.fail("TEST_DATABASE_URL must be a disposable PostgreSQL database")
    schema = "dq_test_" + uuid.uuid4().hex
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_db(make_url(url).update_query_dict({"options": f"-csearch_path={schema}"}))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


def test_validation_failure_rolls_back_entire_run(quality_engine, hand_data):
    bundle = make_bundle(hand_data, "rollback")
    bundle.data["medicines"][0]["name"] = ""
    stage(quality_engine, bundle)
    with quality_engine.begin() as conn:
        if quality_engine.dialect.name == "sqlite":
            conn.execute(
                text("""CREATE TRIGGER test_abort BEFORE INSERT ON dq_run_findings
              BEGIN SELECT RAISE(ABORT,'forced validation persistence failure'); END""")
            )
        else:
            conn.execute(
                text("""CREATE FUNCTION test_abort() RETURNS trigger LANGUAGE plpgsql AS $$
              BEGIN RAISE EXCEPTION 'forced validation persistence failure'; END; $$""")
            )
            conn.execute(
                text(
                    "CREATE TRIGGER test_abort BEFORE INSERT ON dq_run_findings FOR EACH "
                    "ROW EXECUTE FUNCTION test_abort()"
                )
            )
    with pytest.raises(SQLAlchemyError):
        validate_dataset(quality_engine, "rollback")
    with quality_engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(runs)) == 0
        assert conn.scalar(select(func.count()).select_from(issues)) == 0
        assert conn.scalar(select(func.count()).select_from(audit)) == 1
        assert conn.scalar(select(datasets.c.status)) == "staged"
        assert not conn.scalar(
            select(func.count()).select_from(records).where(records.c.quarantined.is_(True))
        )


def test_repeated_staging_validation_and_approved_load(quality_engine, hand_data):
    bundle = make_bundle(hand_data, "repeatable")
    assert stage(quality_engine, bundle) == stage(quality_engine, bundle) == 1
    first = validate_dataset(quality_engine, "repeatable")
    second = validate_dataset(quality_engine, "repeatable")
    assert first.overall_score == second.overall_score == 100
    assert approve(quality_engine, "repeatable", 1, "reviewer", "Approved source") == approve(
        quality_engine, "repeatable", 1, "reviewer", "Repeated safe load"
    )
    with quality_engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(records)) == 8
        assert conn.scalar(select(func.count()).select_from(issues)) == 0
        assert conn.scalar(select(func.count()).select_from(tables["sales_items"])) == 1


def test_additive_migration_preserves_legacy_rows(tmp_path):
    path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        # Use v1 metadata by executing a representative pre-migration medicine table and row.
        conn.execute(
            text(
                "CREATE TABLE medicines (id INTEGER PRIMARY KEY, category_id INTEGER NOT "
                "NULL, name VARCHAR(120) NOT NULL, sku VARCHAR(30) NOT NULL, "
                "dosage_form VARCHAR(30) NOT NULL, list_price NUMERIC(12,2) NOT NULL)"
            )
        )
        conn.execute(
            text("INSERT INTO medicines VALUES (1,1,'SYN Legacy','SYN-LEGACY','Tablet',42)")
        )
    engine.dispose()
    migrated = create_db(f"sqlite:///{path}")
    with migrated.connect() as conn:
        row = conn.execute(select(tables["medicines"])).mappings().one()
        assert row["list_price"] == 42
        assert row["name"] == "SYN Legacy"
        assert row["manufacturer"] is None
    create_db(f"sqlite:///{path}")
