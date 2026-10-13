"""Transactional events, atomic artifacts and process-wide exclusion."""

import fcntl
import hashlib
import json
import logging
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import text

from pharma_suite.automation.schema import events
from pharma_suite.quality.store import now

log = logging.getLogger(__name__)


class RoleBusyError(RuntimeError):
    pass


def record_event(conn, run_id, stage, event, details=None):
    value = {
        "execution_id": run_id,
        "stage": stage,
        "event": event,
        "details_json": details or {},
        "occurred_at": now(),
    }
    conn.execute(events.insert().values(**value))
    log.info(
        json.dumps({"event": event, "execution_id": run_id, "stage": stage, **(details or {})})
    )


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_write(path, write):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    os.close(fd)
    try:
        write(Path(temporary))
        with open(temporary, "rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def safe_artifact(config, filename, expected_hash):
    root = Path(config.report_dir).resolve()
    candidate = (root / filename).resolve()
    if candidate.parent != root or Path(filename).name != filename:
        raise ValueError("Unsafe artifact path")
    if not candidate.is_file() or digest(candidate) != expected_hash:
        raise ValueError("Artifact absent or checksum mismatch")
    return candidate


@contextmanager
def exclusive(engine, config, key):
    if engine.dialect.name == "postgresql":
        conn = engine.connect()
        acquired = False
        try:
            acquired = bool(conn.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}))
            conn.commit()
            if not acquired:
                raise RoleBusyError("Another process owns this automation role")
            yield conn
        finally:
            if acquired:
                conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                conn.commit()
            conn.close()
    else:
        Path(config.report_dir).mkdir(parents=True, exist_ok=True)
        with open(Path(config.report_dir) / f".role-{key}.lock", "a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RoleBusyError("Another process owns this automation role") from exc
            try:
                yield None
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
