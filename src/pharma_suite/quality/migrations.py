"""Additive v2 migration, preserving Phase 1 rows and business values."""

from sqlalchemy import inspect, select, text

from pharma_suite.quality.schema import metadata, versions

ADDITIONS = {
    "medicines": {"manufacturer": "VARCHAR(120)"},
    "distributors": {"contact_email": "VARCHAR(254)"},
    "inventory": {"is_sellable": "BOOLEAN"},
}


def migrate(engine) -> None:
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(71012025)"))
        for table, columns in ADDITIONS.items():
            present = {c["name"] for c in inspect(conn).get_columns(table)}
            for column, kind in columns.items():
                if column not in present:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {kind}"))
        metadata.create_all(conn)
        if not conn.scalar(select(versions.c.version).where(versions.c.version == 2)):
            conn.execute(
                versions.insert().values(version=2, name="Phase 2 staging, validation and audit")
            )
