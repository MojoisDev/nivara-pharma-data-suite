"""Single bounded attempt. Invoked by the controller, never by Streamlit."""

import argparse
import ctypes
import logging
import os
import signal

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from pharma_suite.automation.config import AutomationConfig
from pharma_suite.automation.schema import executions
from pharma_suite.automation.storage import record_event
from pharma_suite.automation.workflow import pipeline
from pharma_suite.db import create_db


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if "AUTOMATION_CONTROLLER_PID" in os.environ:
        # Linux parent-death signal prevents orphan workers surviving controller SIGKILL.
        if ctypes.CDLL(None).prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
            raise RuntimeError("Cannot arm parent-death protection")
        if os.getppid() != int(os.environ["AUTOMATION_CONTROLLER_PID"]):
            raise SystemExit(1)
    engine = create_db()
    with engine.connect() as conn:
        request = (
            conn.execute(select(executions).where(executions.c.id == args.run_id)).mappings().one()
        )
    try:
        result = {
            "ok": True,
            **pipeline(
                engine, args.run_id, AutomationConfig.model_validate(request["config_json"])
            ),
        }
    except Exception as exc:
        result = {
            "ok": False,
            "error_type": type(exc).__name__,
            "retryable": isinstance(exc, (OperationalError, OSError)),
        }
    with engine.begin() as conn:
        conn.execute(
            executions.update().where(executions.c.id == args.run_id).values(result_json=result)
        )
        record_event(conn, args.run_id, "worker", "attempt_result", result)
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
