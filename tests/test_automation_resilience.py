import sys
import time
from unittest.mock import patch

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from pharma_suite.automation.config import AutomationConfig
from pharma_suite.automation.mail import deliver
from pharma_suite.automation.schema import alerts, attempts, emails, executions, reports
from pharma_suite.automation.storage import exclusive
from pharma_suite.automation.workflow import enqueue, execute, execute_inline, run_bounded
from pharma_suite.db import create_db, ingest


@pytest.fixture
def env(tmp_path, hand_data):
    engine = create_db(f"sqlite:///{tmp_path}/resilience.db")
    ingest(engine, hand_data)
    config = AutomationConfig(
        report_dir=str(tmp_path / "reports"),
        retry_delay_seconds=0,
        timeout_seconds=10,
        assessment_at="2026-01-01T12:00:00+00:00",
    )
    return engine, config


def test_hard_timeout_kills_child_process():
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        run_bounded([sys.executable, "-c", "import time; time.sleep(30)"], 0.05)
    assert time.monotonic() - started < 5


def test_retry_bound_and_timeout_history(env):
    engine, config = env
    run_id = enqueue(engine, "daily", "timeout", "reviewer", "timeout probe", config)
    with patch("pharma_suite.automation.workflow.run_bounded", side_effect=TimeoutError):
        execute(engine, run_id, config)
    with engine.connect() as conn:
        assert conn.scalar(select(executions.c.status)) == "timed_out"
        assert conn.scalar(select(func.count()).select_from(attempts)) == 3
        assert conn.scalar(select(func.count()).select_from(reports)) == 0
        assert (
            conn.scalar(
                select(func.count()).select_from(alerts).where(alerts.c.kind == "workflow_failure")
            )
            == 1
        )


def test_transient_worker_failure_then_real_subprocess_succeeds(env):
    engine, config = env
    run_id = enqueue(engine, "daily", "retry-success", "reviewer", "retry probe", config)
    real = run_bounded
    calls = 0

    def transient(command, timeout, env=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return 75
        return real(command, timeout, env)

    with patch("pharma_suite.automation.workflow.run_bounded", side_effect=transient):
        execute(engine, run_id, config)
    with engine.connect() as conn:
        row = conn.execute(select(executions)).mappings().one()
        assert row["status"] == "succeeded"
        assert row["attempts"] == 2
        assert conn.scalar(select(func.count()).select_from(reports)) == 1


def test_process_exclusion_prevents_second_owner(env):
    engine, config = env
    with exclusive(engine, config, 71033025), pytest.raises(RuntimeError):
        with exclusive(engine, config, 71033025):
            pytest.fail("Second scheduler owner must not enter")


def test_request_insert_failure_leaves_no_partial_events(env):
    engine, config = env
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TRIGGER test_abort BEFORE INSERT ON auto_events BEGIN "
                "SELECT RAISE(ABORT,'forced'); END"
            )
        )
    with pytest.raises(SQLAlchemyError):
        enqueue(engine, "daily", "db-failure", "reviewer", "rollback probe", config)
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(executions)) == 0


def test_report_file_integrity_and_formula_injection(env):
    from pharma_suite.automation.reporting import report_path, safe_cell

    engine, config = env
    assert safe_cell('=WEBSERVICE("https://example.invalid")').startswith("'")
    run_id = enqueue(engine, "daily", "integrity", "reviewer", "artifact probe", config)
    execute_inline(engine, run_id, config)
    with engine.connect() as conn:
        report_id = conn.scalar(select(reports.c.id))
    path = report_path(engine, report_id, config)
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        report_path(engine, report_id, config)


class MockSMTP:
    failures = 0
    mode = "transient"

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self, **kwargs):
        pass

    def send_message(self, message, **kwargs):
        import smtplib

        MockSMTP.failures += 1
        if self.mode == "uncertain":
            raise smtplib.SMTPServerDisconnected("Synthetic ambiguous disconnect")
        if MockSMTP.failures < 2:
            raise smtplib.SMTPDataError(451, b"Synthetic temporary failure")
        return {}


def smtp_config(monkeypatch):
    monkeypatch.setenv("MAIL_MODE", "smtp")
    monkeypatch.setenv("SMTP_HOST", "localhost")
    monkeypatch.setenv("SMTP_TLS", "none")
    monkeypatch.setenv("SMTP_RECIPIENTS", "reviewer@synthetic.invalid")
    monkeypatch.setenv("SMTP_ALLOWED_RECIPIENTS", "reviewer@synthetic.invalid")
    monkeypatch.setattr("smtplib.SMTP", MockSMTP)
    MockSMTP.failures = 0
    MockSMTP.mode = "transient"


def test_mock_smtp_transient_retry_is_persisted(env, monkeypatch):
    engine, config = env
    smtp_config(monkeypatch)
    run_id = enqueue(engine, "daily", "mock-smtp", "reviewer", "mail probe", config)
    execute_inline(engine, run_id, config)
    with engine.connect() as conn:
        row = conn.execute(select(emails)).mappings().one()
        assert row["status"] == "sent"
        assert row["attempts"] == 2
    assert deliver(engine, row["id"], config) == "sent"


def test_smtp_ambiguous_disconnect_not_retried(env, monkeypatch):
    engine, config = env
    smtp_config(monkeypatch)
    MockSMTP.mode = "uncertain"
    run_id = enqueue(engine, "daily", "ambiguous-smtp", "reviewer", "mail probe", config)
    execute_inline(engine, run_id, config)
    with engine.connect() as conn:
        row = conn.execute(select(emails)).mappings().one()
        assert row["status"] == "uncertain"
        assert row["attempts"] == 1
    assert deliver(engine, row["id"], config) == "uncertain"


def test_external_smtp_blocked_without_opt_in(env, monkeypatch):
    from pharma_suite.automation.mail import delivery_policy

    monkeypatch.setenv("SMTP_HOST", "smtp.example.invalid")
    monkeypatch.setenv("SMTP_ALLOWED_RECIPIENTS", "person@example.invalid")
    monkeypatch.setenv("SMTP_ALLOW_EXTERNAL", "false")
    with pytest.raises(ValueError, match="disabled"):
        delivery_policy(["person@example.invalid"])


def test_mail_uncertainty_marks_workflow_failed(env, monkeypatch):
    engine, config = env
    smtp_config(monkeypatch)
    MockSMTP.mode = "uncertain"
    run_id = enqueue(engine, "daily", "delivery-failure", "reviewer", "mail probe", config)
    execute_inline(engine, run_id, config)
    with engine.connect() as conn:
        assert conn.scalar(select(executions.c.status)) == "failed"


def test_critical_production_validation_blocks_report(env):
    from pharma_suite.schema import tables

    engine, config = env
    with engine.begin() as conn:
        conn.execute(tables["inventory"].update().values(is_sellable=True))
    run_id = enqueue(engine, "daily", "critical-stock", "reviewer", "critical probe", config)
    execute_inline(engine, run_id, config)
    with engine.connect() as conn:
        assert conn.scalar(select(executions.c.status)) == "failed"
        assert conn.scalar(select(func.count()).select_from(reports)) == 0
        assert (
            conn.scalar(
                select(func.count()).select_from(alerts).where(alerts.c.kind == "expired_sellable")
            )
            == 1
        )


def test_retry_does_not_reuse_report_for_changed_snapshot(env):
    from pharma_suite.automation.reporting import write_report

    engine, config = env
    run_id = enqueue(engine, "daily", "snapshot-guard", "reviewer", "report probe", config)
    execute_inline(engine, run_id, config)
    with pytest.raises(ValueError, match="snapshot"):
        write_report(engine, run_id, config, {}, None, None, "changed-source-hash", None)


def test_atomic_write_preserves_old_file_on_failure(tmp_path):
    from pharma_suite.automation.storage import atomic_write

    path = tmp_path / "report.xlsx"
    path.write_bytes(b"original")

    def broken(temporary):
        temporary.write_bytes(b"partial")
        raise OSError("Synthetic disk failure")

    with pytest.raises(OSError):
        atomic_write(path, broken)
    assert path.read_bytes() == b"original"
    assert not list(tmp_path.glob(".pending-*"))


def test_invalid_mail_configuration_leaves_failed_job_without_crashing(env, monkeypatch):
    engine, config = env
    monkeypatch.setenv("MAIL_MODE", "unknown")
    run_id = enqueue(
        engine, "daily", "mail-config-failure", "reviewer", "Configuration probe", config
    )
    execute_inline(engine, run_id, config)
    with engine.connect() as conn:
        assert conn.scalar(select(executions.c.status)) == "failed"


def test_scheduler_defers_to_manual_controller_without_losing_request(env):
    from pharma_suite.automation.scheduler import drain_once

    engine, config = env
    run_id = enqueue(engine, "daily", "busy-controller", "reviewer", "Concurrency probe", config)
    with exclusive(engine, config, 71032025):
        assert not drain_once(engine, config)
    with engine.connect() as conn:
        assert conn.scalar(select(executions.c.status).where(executions.c.id == run_id)) == "queued"
    assert drain_once(engine, config)
    with engine.connect() as conn:
        assert conn.scalar(select(executions.c.status)) == "succeeded"


def test_timeout_does_not_retain_previous_attempt_result(env):
    engine, config = env
    config = config.model_copy(update={"max_attempts": 2})
    run_id = enqueue(engine, "daily", "stale-result", "reviewer", "Attempt result probe", config)
    calls = 0

    def attempt(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            with engine.begin() as conn:
                conn.execute(
                    executions.update()
                    .where(executions.c.id == run_id)
                    .values(
                        result_json={
                            "ok": False,
                            "error_type": "OperationalError",
                            "retryable": True,
                        }
                    )
                )
            return 1
        raise TimeoutError

    with patch("pharma_suite.automation.workflow.run_bounded", side_effect=attempt):
        execute(engine, run_id, config)
    with engine.connect() as conn:
        row = conn.execute(select(executions)).mappings().one()
        assert row["status"] == "timed_out"
        assert row["result_json"] is None


def test_interrupted_execution_records_elapsed_duration(env):
    from datetime import timedelta

    from pharma_suite.automation.workflow import begin_attempt, claim, recover_interrupted
    from pharma_suite.quality.store import now

    engine, config = env
    run_id = enqueue(engine, "daily", "interrupted", "reviewer", "Recovery probe", config)
    claim(engine, run_id)
    begin_attempt(engine, run_id, 1)
    with engine.begin() as conn:
        conn.execute(
            executions.update()
            .where(executions.c.id == run_id)
            .values(started_at=now() - timedelta(seconds=5))
        )
    with exclusive(engine, config, 71032025):
        recover_interrupted(engine, config)
    with engine.connect() as conn:
        row = conn.execute(select(executions)).mappings().one()
        assert row["status"] == "failed"
        assert row["duration_seconds"] >= 5
