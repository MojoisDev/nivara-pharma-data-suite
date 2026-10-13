"""Durable requests and ordered execution; separate scheduler owns bounded subprocess runs."""

import os
import signal
import subprocess
import sys
import time
import uuid
from datetime import timezone

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from pharma_suite.automation.alerts import evaluate_alerts
from pharma_suite.automation.config import AutomationConfig
from pharma_suite.automation.mail import deliver, prepare_email
from pharma_suite.automation.reporting import calculate, snapshot, write_report
from pharma_suite.automation.schema import attempts, executions
from pharma_suite.automation.storage import exclusive, record_event
from pharma_suite.quality.store import (
    fingerprint,
    lock,
    now,
    review_identity,
    stage,
    validate_dataset,
)


class CriticalQualityError(ValueError):
    pass


class MailDeliveryError(ValueError):
    pass


def enqueue(engine, kind, key, actor, notes, config, start=None, end=None):
    review_identity(actor, notes)
    if kind not in {"daily", "weekly"} or not key or len(key) > 160:
        raise ValueError("Supply daily/weekly and an idempotency key of 1–160 characters")
    if (start is None) != (end is None):
        raise ValueError("Supply both start and end dates or neither")
    if start and start > end:
        raise ValueError("Start date must precede end date")
    params = {
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
    }
    value = {"kind": kind, "params": params, "config": config.model_dump(mode="json")}
    request_hash = fingerprint(value)
    with engine.begin() as conn:
        lock(conn)
        existing = (
            conn.execute(select(executions).where(executions.c.idempotency_key == key))
            .mappings()
            .first()
        )
        if existing:
            if existing["request_hash"] != request_hash:
                raise ValueError("Idempotency key already used for a different request")
            return existing["id"]
        run_id = str(uuid.uuid4())
        conn.execute(
            executions.insert().values(
                id=run_id,
                idempotency_key=key,
                request_hash=request_hash,
                kind=kind,
                actor=actor,
                notes=notes,
                params_json=params,
                config_json=value["config"],
                status="queued",
                created_at=now(),
                attempts=0,
            )
        )
        record_event(conn, run_id, "queue", "enqueued", {"kind": kind, "actor": actor})
    return run_id


def claim(engine, run_id):
    with engine.begin() as conn:
        lock(conn)
        row = conn.execute(select(executions).where(executions.c.id == run_id)).mappings().first()
        if not row:
            raise ValueError("Unknown execution")
        if row["status"] != "queued":
            return None
        conn.execute(
            executions.update()
            .where(executions.c.id == run_id)
            .values(status="running", started_at=now())
        )
        return dict(row)


def begin_attempt(engine, run_id, number):
    with engine.begin() as conn:
        conn.execute(
            executions.update()
            .where(executions.c.id == run_id)
            .values(attempts=number, result_json=None)
        )
        conn.execute(
            attempts.insert().values(
                execution_id=run_id, number=number, status="running", started_at=now()
            )
        )
        record_event(conn, run_id, "execution", "attempt_started", {"attempt": number})


def end_attempt(engine, run_id, number, status, duration, error=None):
    with engine.begin() as conn:
        conn.execute(
            attempts.update()
            .where(attempts.c.execution_id == run_id, attempts.c.number == number)
            .values(status=status, duration_seconds=duration, completed_at=now(), error_type=error)
        )
        record_event(
            conn, run_id, "execution", "attempt_" + status, {"attempt": number, "error_type": error}
        )


def completed(engine, run_id, stage_name, details=None):
    with engine.begin() as conn:
        record_event(conn, run_id, stage_name, "stage_completed", details)


def pipeline(engine, run_id, config):
    with engine.connect() as conn:
        request = conn.execute(select(executions).where(executions.c.id == run_id)).mappings().one()
    bundle, facts, content_hash, cutoff = snapshot(engine)
    stage(engine, bundle)
    quality = validate_dataset(engine, bundle.name, reference=config.assessment_at or now())
    completed(
        engine,
        run_id,
        "validation",
        {"quality_run_id": quality.run_id, "snapshot_hash": content_hash},
    )
    if config.stop_on_critical and any(f.severity == "critical" for f in quality.findings):
        raise CriticalQualityError("Critical quality findings block report publication")
    report, start, end = calculate(
        facts,
        request["kind"],
        request["params_json"]["start"],
        request["params_json"]["end"],
        cutoff,
        config,
    )
    completed(engine, run_id, "analytics", {"start": start.isoformat(), "end": end.isoformat()})
    artifact = write_report(engine, run_id, config, report, start, end, content_hash, quality)
    completed(engine, run_id, "report", {"report_id": artifact["id"]})
    changes = evaluate_alerts(engine, config)
    completed(engine, run_id, "alerts", {"changed_alerts": len(changes)})
    email_id = prepare_email(engine, run_id, config, artifact)
    delivery = deliver(engine, email_id, config)
    completed(engine, run_id, "email", {"email_id": email_id, "delivery_status": delivery})
    if delivery in {"failed", "uncertain"}:
        raise MailDeliveryError("Email delivery requires explicit review")
    return {
        "report_id": artifact["id"],
        "email_id": email_id,
        "email_status": delivery,
        "quality_run_id": artifact["summary_json"]["quality_run_id"],
        "snapshot_hash": content_hash,
    }


def finish(engine, run_id, status, duration, config, result=None, error=None):
    with engine.begin() as conn:
        conn.execute(
            executions.update()
            .where(executions.c.id == run_id)
            .values(
                status=status,
                completed_at=now(),
                duration_seconds=duration,
                error_type=error,
                result_json=result,
            )
        )
        record_event(
            conn, run_id, "execution", status, {"error_type": error, "duration_seconds": duration}
        )
    # Terminal status is persisted before evaluating workflow failure/recovery alerts.
    evaluate_alerts(engine, config)
    if status != "succeeded":
        try:
            email_id = prepare_email(engine, run_id, config, failure=error or status)
            deliver(engine, email_id, config)
        except (ValueError, OSError) as exc:
            with engine.begin() as conn:
                record_event(
                    conn,
                    run_id,
                    "email",
                    "failure_notification_rejected",
                    {"error_type": type(exc).__name__},
                )


def execute_inline(engine, run_id, config):
    """Same pipeline for deterministic tests; deployment uses the hard-timeout subprocess runner."""
    with exclusive(engine, config, 71032025):
        request = claim(engine, run_id)
        if not request:
            return
        started = time.monotonic()
        begin_attempt(engine, run_id, 1)
        try:
            result = pipeline(engine, run_id, config)
        except (ValueError, SQLAlchemyError, OSError) as exc:
            end_attempt(engine, run_id, 1, "failed", time.monotonic() - started, type(exc).__name__)
            finish(
                engine,
                run_id,
                "failed",
                time.monotonic() - started,
                config,
                error=type(exc).__name__,
            )
        else:
            end_attempt(engine, run_id, 1, "succeeded", time.monotonic() - started)
            finish(engine, run_id, "succeeded", time.monotonic() - started, config, result)


def run_bounded(command, timeout, env=None):
    child = subprocess.Popen(
        command,
        env=env,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        return child.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=2)
        raise TimeoutError("Workflow subprocess exceeded its deadline") from None
    finally:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()


def execute(engine, run_id, config=None):
    config = config or AutomationConfig()
    with exclusive(engine, config, 71032025):
        request = claim(engine, run_id)
        if not request:
            return
        config = AutomationConfig.model_validate(request["config_json"])
        started = time.monotonic()
        error = None
        result = None
        status = "failed"
        for number in range(1, config.max_attempts + 1):
            result = None
            begin_attempt(engine, run_id, number)
            attempt_start = time.monotonic()
            try:
                code = run_bounded(
                    [sys.executable, "-m", "pharma_suite.automation.worker", "--run-id", run_id],
                    config.timeout_seconds,
                    {
                        **os.environ,
                        "DATABASE_URL": engine.url.render_as_string(hide_password=False),
                        "AUTOMATION_CONTROLLER_PID": str(os.getpid()),
                    },
                )
                with engine.connect() as conn:
                    result = conn.scalar(
                        select(executions.c.result_json).where(executions.c.id == run_id)
                    )
                if code == 0 and result and result.get("ok"):
                    status, error = "succeeded", None
                else:
                    error = (result or {}).get("error_type", "WorkerProcessError")
                    status = "failed"
            except TimeoutError:
                status, error = "timed_out", "TimeoutError"
            end_attempt(engine, run_id, number, status, time.monotonic() - attempt_start, error)
            if status == "succeeded" or (result and result.get("retryable") is False):
                break
            if number < config.max_attempts:
                time.sleep(config.retry_delay_seconds)
        finish(engine, run_id, status, time.monotonic() - started, config, result, error)


def recover_interrupted(engine, config):
    """Call only while owning the worker exclusion lock after an unclean restart."""
    with engine.connect() as conn:
        interrupted = (
            conn.execute(select(executions).where(executions.c.status == "running"))
            .mappings()
            .all()
        )
    for request in interrupted:
        run_id = request["id"]
        with engine.begin() as conn:
            conn.execute(
                attempts.update()
                .where(attempts.c.execution_id == run_id, attempts.c.status == "running")
                .values(status="interrupted", completed_at=now(), error_type="WorkerInterrupted")
            )
        started = request["started_at"]
        if started and started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        elapsed = max(0, (now() - started).total_seconds()) if started else None
        finish(
            engine,
            run_id,
            "failed",
            elapsed,
            AutomationConfig.model_validate(request["config_json"]),
            error="WorkerInterrupted",
        )
