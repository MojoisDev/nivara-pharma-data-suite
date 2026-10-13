import os
import threading
import uuid
from datetime import date

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from pharma_suite.automation.alerts import evaluate_alerts
from pharma_suite.automation.config import AutomationConfig
from pharma_suite.automation.scheduler import build_scheduler
from pharma_suite.automation.schema import alerts, executions, reports
from pharma_suite.automation.storage import exclusive
from pharma_suite.automation.workflow import enqueue, execute, execute_inline
from pharma_suite.db import create_db, ingest
from pharma_suite.schema import tables


@pytest.fixture(params=["sqlite", "postgres"])
def transaction_env(request, tmp_path, hand_data):
    config = AutomationConfig(
        report_dir=str(tmp_path / "reports"),
        retry_delay_seconds=0,
        assessment_at="2026-01-01T12:00:00+00:00",
        low_stock_units=500,
    )
    admin = None
    if request.param == "postgres":
        url = os.getenv("TEST_DATABASE_URL")
        if not url:
            pytest.skip("TEST_DATABASE_URL required for PostgreSQL automation tests")
        if not url.startswith("postgresql"):
            pytest.fail("TEST_DATABASE_URL must be a disposable PostgreSQL database")
        schema = "auto_test_" + uuid.uuid4().hex
        admin = create_engine(url)
        with admin.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA {schema}"))
        engine = create_db(make_url(url).update_query_dict({"options": f"-csearch_path={schema}"}))
    else:
        engine = create_db(f"sqlite:///{tmp_path}/transactions.db")
    ingest(engine, hand_data)
    try:
        yield engine, config
    finally:
        engine.dispose()
        if admin:
            with admin.begin() as conn:
                conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
            admin.dispose()


def fail_insert(engine, table):
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            conn.execute(
                text(
                    "CREATE FUNCTION abort_insert() RETURNS trigger LANGUAGE plpgsql "
                    "AS $$ BEGIN RAISE EXCEPTION 'Synthetic forced failure'; END; $$"
                )
            )
            conn.execute(
                text(
                    f"CREATE TRIGGER abort_insert BEFORE INSERT ON {table} "
                    "FOR EACH ROW EXECUTE FUNCTION abort_insert()"
                )
            )
        else:
            conn.execute(
                text(
                    f"CREATE TRIGGER abort_insert BEFORE INSERT ON {table} "
                    "BEGIN SELECT RAISE(ABORT,'Synthetic forced failure'); END"
                )
            )


def test_bounded_workflow_on_actual_database_preserves_business_data(transaction_env):
    engine, config = transaction_env
    run_id = enqueue(
        engine,
        "weekly",
        "pg-workflow",
        "reviewer",
        "Database integration",
        config,
        start=date(2025, 1, 1),
        end=date(2025, 12, 31),
    )
    execute(engine, run_id, config)
    with engine.connect() as conn:
        assert conn.scalar(select(executions.c.status)) == "succeeded"
        assert conn.scalar(select(func.count()).select_from(tables["sales_items"])) == 1
        assert conn.scalar(select(reports.c.summary_json))["revenue"] == "150"
        assert conn.scalar(select(func.count()).select_from(alerts)) >= 1


def test_second_scheduler_owner_rejected_by_database(transaction_env):
    engine, config = transaction_env
    with exclusive(engine, config, 71033025), pytest.raises(RuntimeError):
        with exclusive(engine, config, 71033025):
            pytest.fail("Duplicate scheduler entered")


def test_report_registry_failure_does_not_change_business_rows(transaction_env):
    engine, config = transaction_env
    fail_insert(engine, "auto_reports")
    run_id = enqueue(
        engine, "daily", "report-db-failure", "reviewer", "Rollback integration", config
    )
    execute_inline(engine, run_id, config)
    with engine.connect() as conn:
        assert conn.scalar(select(executions.c.status)) == "failed"
        assert conn.scalar(select(func.count()).select_from(reports)) == 0
        assert conn.scalar(select(tables["inventory"].c.quantity)) == 90


def test_alert_change_and_audit_are_atomic(transaction_env):
    engine, config = transaction_env
    fail_insert(engine, "auto_alert_events")
    with pytest.raises(SQLAlchemyError):
        evaluate_alerts(engine, config)
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(alerts)) == 0


def test_scheduler_callback_enqueues_durable_request(transaction_env):
    from pharma_suite.quality.store import now

    engine, config = transaction_env
    ready = threading.Event()

    def submit(kind):
        enqueue(engine, kind, "scheduled:" + kind, "scheduler", "Scheduled integration", config)
        ready.set()

    scheduler = build_scheduler(config, submit)
    scheduler.start(paused=True)
    try:
        job = scheduler.get_job("daily")
        assert job.max_instances == 1 and job.coalesce
        job.modify(next_run_time=now())
        scheduler.resume()
        assert ready.wait(5)
        with engine.connect() as conn:
            assert conn.scalar(select(executions.c.status)) == "queued"
    finally:
        scheduler.shutdown()
