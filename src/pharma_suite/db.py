"""Transactional refresh of a dedicated synthetic dataset, never append duplicate rows."""

import json
import logging
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from pharma_suite.generate import TABLE_ORDER, validate
from pharma_suite.schema import metadata, tables

logger = logging.getLogger(__name__)


def database_url() -> str:
    load_dotenv()
    return os.getenv("DATABASE_URL", "sqlite:///data/pharma_demo.db")


def create_db(url: str | None = None) -> Engine:
    engine = create_engine(url or database_url(), pool_pre_ping=True)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def sqlite_fk(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    elif engine.dialect.name != "postgresql":
        raise ValueError("Supported database dialects: PostgreSQL and SQLite demo")
    metadata.create_all(engine)
    from pharma_suite.quality.migrations import migrate

    migrate(engine)
    from pharma_suite.automation.migrations import migrate as migrate_automation

    migrate_automation(engine)
    return engine


def ingest(engine: Engine, data: dict[str, list[dict]]) -> dict[str, int]:
    """Atomic full refresh. Use only the suite's dedicated synthetic database."""
    try:
        validate(data)
    except ValueError:
        logger.error(json.dumps({"event": "ingestion_rejected", "error_type": "ValueError"}))
        raise
    counts = {name: len(data[name]) for name in TABLE_ORDER}
    try:
        with engine.begin() as conn:
            if engine.dialect.name == "postgresql":
                conn.execute(text("SELECT pg_advisory_xact_lock(71012025)"))
            for name in reversed(TABLE_ORDER):
                conn.execute(tables[name].delete())
            for name in TABLE_ORDER:
                rows = data[name]
                for offset in range(0, len(rows), 1000):
                    conn.execute(tables[name].insert(), rows[offset : offset + 1000])
        logger.info(json.dumps({"event": "ingestion_complete", "rows": counts}))
        return counts
    except SQLAlchemyError as exc:
        # Avoid logging database URLs or SQL parameters that might contain credentials.
        logger.error(
            json.dumps({"event": "ingestion_rolled_back", "error_type": type(exc).__name__})
        )
        raise
