import os
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from pharma_suite.analytics import build_report, load_facts
from pharma_suite.db import create_db, ingest
from pharma_suite.generate import generate
from pharma_suite.schema import tables


@pytest.fixture
def pg_engine():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a dedicated disposable PostgreSQL database")
    if not url.startswith("postgresql"):
        pytest.fail("TEST_DATABASE_URL must be PostgreSQL")
    engine = create_db(url)
    yield engine
    engine.dispose()


@pytest.mark.postgres
def test_postgres_idempotence_and_rollback(pg_engine):
    data = generate()
    first = ingest(pg_engine, data)
    assert first == ingest(pg_engine, data)
    invalid = generate()
    invalid["medicines"][0]["list_price"] = -1
    with pytest.raises(IntegrityError):
        ingest(pg_engine, invalid)
    with pg_engine.connect() as conn:
        for name, count in first.items():
            assert conn.scalar(select(func.count()).select_from(tables[name])) == count
        assert (
            conn.scalar(
                select(tables["medicines"].c.list_price).where(tables["medicines"].c.id == 1)
            )
            > 0
        )
        assert (
            conn.scalar(
                text("""SELECT count(*) FROM inventory i JOIN batches b ON b.id=i.batch_id
          WHERE i.quantity <> b.received_quantity - COALESCE(
            (SELECT SUM(quantity) FROM sales_items si WHERE si.batch_id=b.id), 0)""")
            )
            == 0
        )


@pytest.mark.postgres
def test_postgres_sql_hand_verified(pg_engine, hand_data):
    ingest(pg_engine, hand_data)
    params = {
        "start_date": date(2025, 1, 1),
        "end_date": date(2025, 1, 10),
        "risk_cutoff": date(2025, 4, 10),
        "region": None,
        "category": None,
    }
    root = Path(__file__).resolve().parents[1] / "sql" / "queries"
    with pg_engine.connect() as conn:
        results = {
            p.stem: conn.execute(text(p.read_text()), params).mappings().all()
            for p in sorted(root.glob("*.sql"))
        }
    assert results["monthly_revenue"][0]["revenue"] == 150
    assert results["revenue_by_region"][0]["revenue"] == 150
    assert results["revenue_by_category"][0]["revenue"] == 150
    assert results["top_products"][0]["units"] == 10
    assert results["stock_levels"][0]["stock_units"] == 90
    assert results["near_expiry"][0]["stock_units"] == 90
    assert results["stock_at_risk"][0]["risk_value"] == 180
    assert float(results["inventory_turnover"][0]["average_inventory"]) == 190
    assert float(results["inventory_turnover"][0]["turnover"]) == pytest.approx(20 / 190)
    sales, batches = load_facts(pg_engine)
    assert build_report(sales, batches, date(2025, 1, 1), date(2025, 1, 10))["stock_units"] == 90
    # Restore the full synthetic dataset after successful verification.
    ingest(pg_engine, generate())


@pytest.mark.postgres
def test_postgres_sql_matches_filtered_dashboard(pg_engine):
    ingest(pg_engine, generate())
    sales, batches = load_facts(pg_engine)
    root = Path(__file__).resolve().parents[1] / "sql" / "queries"
    params = {
        "start_date": date(2025, 4, 15),
        "end_date": date(2025, 10, 20),
        "risk_cutoff": date(2026, 1, 18),
        "region": "South",
        "category": "Cardiology",
    }
    report = build_report(
        sales, batches, params["start_date"], params["end_date"], ["South"], ["Cardiology"]
    )
    with pg_engine.connect() as conn:
        results = {
            p.stem: conn.execute(text(p.read_text()), params).mappings().all()
            for p in root.glob("*.sql")
        }
    assert sum(r["revenue"] for r in results["monthly_revenue"]) == report["revenue"]
    assert sum(r["stock_units"] for r in results["stock_levels"]) == report["stock_units"]
    assert results["stock_at_risk"][0]["risk_value"] == report["risk_value"]
    assert float(results["inventory_turnover"][0]["average_inventory"]) == pytest.approx(
        report["average_inventory"]
    )
    assert float(results["inventory_turnover"][0]["turnover"]) == pytest.approx(report["turnover"])
