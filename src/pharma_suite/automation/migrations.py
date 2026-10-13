from sqlalchemy import select

from pharma_suite.automation.schema import metadata
from pharma_suite.quality.schema import versions
from pharma_suite.quality.store import lock


def migrate(engine):
    with engine.begin() as conn:
        lock(conn)
        metadata.create_all(conn)
        if not conn.scalar(select(versions.c.version).where(versions.c.version == 3)):
            conn.execute(
                versions.insert().values(version=3, name="Phase 3 reporting, jobs and alerts")
            )
