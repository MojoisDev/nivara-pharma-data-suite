"""One dedicated scheduler; persistent queue survives restart without sharing APScheduler stores."""

import logging
import signal
import threading
import uuid
from datetime import timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, text

from pharma_suite.automation.config import load_config
from pharma_suite.automation.schema import executions, scheduler_state
from pharma_suite.automation.storage import RoleBusyError, exclusive
from pharma_suite.automation.workflow import enqueue, execute, recover_interrupted
from pharma_suite.db import create_db
from pharma_suite.quality.store import fingerprint, now


def schedule_key(kind, instant, config):
    clock = instant.astimezone(ZoneInfo(config.timezone)).strftime("%Y%m%d%H%M")
    return f"schedule:{kind}:{clock}:{fingerprint(config.model_dump(mode='json'))[:12]}"


def build_scheduler(config, submit):
    scheduler = BackgroundScheduler(
        timezone=config.timezone,
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
    )
    for kind, expression in [("daily", config.daily_cron), ("weekly", config.weekly_cron)]:
        scheduler.add_job(
            submit,
            CronTrigger.from_crontab(expression, timezone=config.timezone),
            args=[kind],
            id=kind,
            replace_existing=True,
        )
    return scheduler


def status(engine):
    with engine.connect() as conn:
        row = (
            conn.execute(select(scheduler_state).where(scheduler_state.c.id == "main"))
            .mappings()
            .first()
        )
    if not row:
        return {"status": "not_started", "healthy": False, "jobs": []}
    value = dict(row)
    heartbeat = value["heartbeat_at"]
    if heartbeat.tzinfo is None:
        from datetime import timezone

        heartbeat = heartbeat.replace(tzinfo=timezone.utc)
    value["healthy"] = value["status"] == "running" and now() - heartbeat < timedelta(seconds=45)
    value["jobs"] = value.pop("jobs_json")
    return value


def drain_once(engine, config):
    with engine.connect() as conn:
        run_id = conn.scalar(
            select(executions.c.id)
            .where(executions.c.status == "queued")
            .order_by(executions.c.created_at)
            .limit(1)
        )
    if not run_id:
        return False
    try:
        execute(engine, run_id, config)
    except RoleBusyError:
        return False
    return True


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    engine = create_db()
    config = load_config()
    stopping = threading.Event()
    owner = str(uuid.uuid4())

    def stop(*_):
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with exclusive(engine, config, 71033025) as lease:
        with exclusive(engine, config, 71032025):
            recover_interrupted(engine, config)

        def submit(kind):
            enqueue(
                engine,
                kind,
                schedule_key(kind, now(), config),
                "scheduler",
                f"Configured {kind} schedule",
                config,
            )

        scheduler = build_scheduler(config, submit)
        scheduler.start()

        def heartbeat():
            while not stopping.is_set():
                try:
                    if lease is not None:
                        lease.execute(text("SELECT 1"))
                        lease.commit()
                    jobs = [
                        {
                            "id": job.id,
                            "next_run_time": job.next_run_time.isoformat()
                            if job.next_run_time
                            else None,
                            "trigger": str(job.trigger),
                        }
                        for job in scheduler.get_jobs()
                    ]
                    with engine.begin() as conn:
                        row = conn.scalar(
                            select(scheduler_state.c.id).where(scheduler_state.c.id == "main")
                        )
                        value = dict(
                            owner=owner,
                            status="running",
                            heartbeat_at=now(),
                            jobs_json=jobs,
                            config_json=config.model_dump(mode="json"),
                        )
                        if row:
                            conn.execute(
                                scheduler_state.update()
                                .where(scheduler_state.c.id == "main")
                                .values(**value)
                            )
                        else:
                            conn.execute(scheduler_state.insert().values(id="main", **value))
                except Exception:
                    logging.error('{"event":"scheduler_heartbeat_failed"}')
                    stopping.set()
                stopping.wait(5)

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            while not stopping.is_set():
                if not drain_once(engine, config):
                    stopping.wait(1)
        finally:
            stopping.set()
            scheduler.shutdown(wait=True)
            thread.join(timeout=10)
            with engine.begin() as conn:
                conn.execute(
                    scheduler_state.update()
                    .where(scheduler_state.c.id == "main", scheduler_state.c.owner == owner)
                    .values(status="stopped", heartbeat_at=now())
                )


if __name__ == "__main__":
    main()
