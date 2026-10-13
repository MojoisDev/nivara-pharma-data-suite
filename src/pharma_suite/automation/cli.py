"""Local workflow operations: queue/run, history, alerts, artifacts, mail and scheduler."""

import argparse
import json
import logging
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from pharma_suite.automation.alerts import acknowledge, evaluate_alerts
from pharma_suite.automation.config import load_config
from pharma_suite.automation.mail import deliver
from pharma_suite.automation.reporting import report_path
from pharma_suite.automation.scheduler import status
from pharma_suite.automation.schema import alerts, emails, executions, reports
from pharma_suite.automation.storage import atomic_write, safe_artifact
from pharma_suite.automation.workflow import enqueue, execute
from pharma_suite.db import create_db


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("trigger", "run"):
        command = sub.add_parser(action)
        command.add_argument("--kind", choices=["daily", "weekly"], default="daily")
        command.add_argument("--key", required=True)
        command.add_argument("--actor", required=True)
        command.add_argument("--notes", required=True)
        command.add_argument("--start", type=date.fromisoformat)
        command.add_argument("--end", type=date.fromisoformat)
    listing = sub.add_parser("list")
    listing.add_argument(
        "--entity", choices=["executions", "reports", "alerts", "emails"], default="executions"
    )
    sub.add_parser("scheduler-status")
    sub.add_parser("health")
    sub.add_parser("schedule")
    serving = sub.add_parser("serve")
    serving.add_argument("--host", default="127.0.0.1")
    serving.add_argument("--port", type=int, default=8503)
    sub.add_parser("evaluate-alerts")
    ack = sub.add_parser("acknowledge")
    ack.add_argument("--id", type=int, required=True)
    ack.add_argument("--actor", required=True)
    ack.add_argument("--notes", required=True)
    download = sub.add_parser("report")
    download.add_argument("--id", required=True)
    download.add_argument("--output", type=Path)
    preview = sub.add_parser("email-preview")
    preview.add_argument("--id", required=True)
    delivery = sub.add_parser("deliver-email")
    delivery.add_argument("--id", required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        engine = create_db()
        config = load_config()
        result = {}
        if args.action in {"trigger", "run"}:
            run_id = enqueue(
                engine, args.kind, args.key, args.actor, args.notes, config, args.start, args.end
            )
            if args.action == "run":
                execute(engine, run_id, config)
            with engine.connect() as conn:
                result = dict(
                    conn.execute(select(executions).where(executions.c.id == run_id))
                    .mappings()
                    .one()
                )
            print(json.dumps(result, default=str, indent=2))
            if args.action == "run" and result["status"] != "succeeded":
                raise SystemExit(1)
            return
        if args.action == "list":
            table = {
                "executions": executions,
                "reports": reports,
                "alerts": alerts,
                "emails": emails,
            }[args.entity]
            with engine.connect() as conn:
                result = [
                    dict(r)
                    for r in conn.execute(
                        select(table).order_by(table.c.id.desc()).limit(100)
                    ).mappings()
                ]
        elif args.action in {"scheduler-status", "health"}:
            result = status(engine)
            if args.action == "health":
                if not result["healthy"]:
                    raise SystemExit(1)
                return
        elif args.action == "schedule":
            from pharma_suite.automation.scheduler import main as schedule

            schedule()
            return
        elif args.action == "serve":
            from pharma_suite.automation.api import make_server

            server = make_server(engine, config, args.host, args.port)
            try:
                server.serve_forever()
            finally:
                server.server_close()
            return
        elif args.action == "evaluate-alerts":
            result = {"changed_alert_ids": evaluate_alerts(engine, config)}
        elif args.action == "acknowledge":
            acknowledge(engine, args.id, args.actor, args.notes)
            result = {"id": args.id, "status": "acknowledged"}
        elif args.action == "report":
            path = report_path(engine, args.id, config)
            if args.output:
                atomic_write(
                    args.output, lambda temporary: temporary.write_bytes(path.read_bytes())
                )
                path = args.output.resolve()
            result = {"report_id": args.id, "path": str(path)}
        elif args.action == "email-preview":
            with engine.connect() as conn:
                row = conn.execute(select(emails).where(emails.c.id == args.id)).mappings().first()
            if not row:
                raise ValueError("Unknown email")
            result = {
                "status": row["status"],
                "subject": row["subject"],
                "body": row["body_text"],
                "eml_path": str(safe_artifact(config, row["filename"], row["sha256"])),
            }
        elif args.action == "deliver-email":
            result = {"status": deliver(engine, args.id, config)}
        print(json.dumps(result, default=str, indent=2))
    except (ValueError, OSError, RuntimeError, SQLAlchemyError) as exc:
        logging.error(
            json.dumps(
                {
                    "event": "automation_command_failed",
                    "error_type": type(exc).__name__,
                    "message": "Operation rejected or unavailable. Check configuration, history "
                    "and database.",
                }
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
