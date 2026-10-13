from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from pharma_suite.analytics import build_report, load_facts
from pharma_suite.db import create_db, ingest
from pharma_suite.generate import generate, validate
from pharma_suite.schema import tables


def test_deterministic_and_reconciled():
    data = generate()
    assert data == generate()
    assert len(data["medicines"]) == 120
    assert len(data["sales"]) >= 8000
    assert {s["sale_date"].strftime("%Y-%m") for s in data["sales"]} == {
        f"{year}-{month:02}" for year in (2024, 2025) for month in range(1, 13)
    }
    validate(data)
    sold = {}
    for item in data["sales_items"]:
        sold[item["batch_id"]] = sold.get(item["batch_id"], 0) + item["quantity"]
    for batch, stock in zip(data["batches"], data["inventory"], strict=True):
        assert batch["received_quantity"] - sold.get(batch["id"], 0) == stock["quantity"]


def test_invalid_snapshot_is_rejected():
    data = generate()
    data["inventory"][0]["quantity"] += 1
    with pytest.raises(ValueError, match="reconcil"):
        validate(data)


def test_ingestion_is_idempotent_and_atomic(tmp_path):
    engine = create_db(f"sqlite:///{tmp_path}/test.db")
    data = generate()
    assert ingest(engine, data) == ingest(engine, data)
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(tables["sales"])) == len(data["sales"])
    bad = generate(seed=18)
    bad["medicines"][0]["category_id"] = 9999
    with pytest.raises((ValueError, IntegrityError)):
        ingest(engine, bad)
    with engine.connect() as conn:
        assert (
            conn.scalar(select(tables["medicines"].c.name).where(tables["medicines"].c.id == 1))
            == data["medicines"][0]["name"]
        )


def test_foreign_keys_and_checks(tmp_path):
    engine = create_db(f"sqlite:///{tmp_path}/test.db")
    ingest(engine, generate())
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(tables["inventory"].update().values(quantity=-1))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(tables["medicines"].update().values(category_id=999))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(tables["sales_items"].update().values(warehouse_id=999))


def test_hand_verified_kpis(hand_data):
    engine = create_db("sqlite://")
    ingest(engine, hand_data)
    sales, batches = load_facts(engine)
    report = build_report(sales, batches, date(2025, 1, 1), date(2025, 1, 10))
    assert report["revenue"] == Decimal("150.00")
    assert report["units"] == 10
    assert report["stock_units"] == 90
    assert report["risk_value"] == Decimal("180.00")
    # 100 at cost 2 on Jan 1; 10 sold Jan 6: (5*200 + 5*180)/10 = 190.
    assert report["average_inventory"] == pytest.approx(190)
    assert report["turnover"] == pytest.approx(20 / 190)
    assert report["monthly"]["revenue"].tolist() == [150.0]
    assert report["categories"]["revenue"].tolist() == [150.0]
    assert report["regions"]["revenue"].tolist() == [150.0]
    early = build_report(sales, batches, date(2025, 1, 1), date(2025, 1, 5))
    assert early["stock_units"] == 100
    assert early["revenue"] == 0
    assert early["turnover"] == 0
    empty = build_report(sales, batches, date(2025, 1, 1), date(2025, 1, 10), regions=[])
    assert empty["stock_units"] == empty["revenue"] == 0


def test_future_receipts_and_expiry_boundaries(hand_data):
    hand_data["batches"][0]["expiry_date"] = date(2025, 1, 10)
    engine = create_db("sqlite://")
    ingest(engine, hand_data)
    sales, batches = load_facts(engine)
    before = build_report(sales, batches, date(2024, 12, 1), date(2024, 12, 31))
    assert before["stock_units"] == 0
    on = build_report(sales, batches, date(2025, 1, 1), date(2025, 1, 10))
    assert on["expired_units"] == 0
    after = build_report(sales, batches, date(2025, 1, 1), date(2025, 1, 11))
    assert after["expired_units"] == 90


def test_repeated_sales_do_not_duplicate_stock(hand_data):
    hand_data["sales"].append(
        {
            "id": 2,
            "distributor_id": 1,
            "warehouse_id": 1,
            "sale_date": date(2025, 1, 10),
            "invoice_number": "SYN-INV002",
        }
    )
    hand_data["sales_items"].append(
        {
            "id": 2,
            "sale_id": 2,
            "warehouse_id": 1,
            "batch_id": 1,
            "quantity": 5,
            "unit_price": Decimal("10.00"),
        }
    )
    hand_data["inventory"][0]["quantity"] = 85
    engine = create_db("sqlite://")
    ingest(engine, hand_data)
    sales, batches = load_facts(engine)
    report = build_report(sales, batches, date(2025, 1, 1), date(2025, 1, 10))
    assert report["revenue"] == 200
    assert report["stock_units"] == 85
    assert report["stock_value"] == 170
    assert report["average_inventory"] == 189
    assert report["turnover"] == pytest.approx(30 / 189)
    assert report["invoices"] == 2


@pytest.mark.parametrize(
    "expiry,near,expired,risk",
    [
        (date(2025, 1, 9), 0, 90, 180),
        (date(2025, 1, 10), 90, 0, 180),
        (date(2025, 4, 10), 90, 0, 180),
        (date(2025, 4, 11), 0, 0, 0),
    ],
)
def test_expiry_horizon_is_inclusive(hand_data, expiry, near, expired, risk):
    hand_data["batches"][0]["expiry_date"] = expiry
    engine = create_db("sqlite://")
    ingest(engine, hand_data)
    report = build_report(*load_facts(engine), date(2025, 1, 1), date(2025, 1, 10))
    assert report["near_expiry_units"] == near
    assert report["expired_units"] == expired
    assert report["risk_value"] == risk


def test_sale_after_expiry_is_rejected(hand_data):
    hand_data["batches"][0]["expiry_date"] = date(2025, 1, 5)
    with pytest.raises(ValueError, match="expiry window"):
        validate(hand_data)


def test_invalid_reporting_window_is_rejected(hand_data):
    engine = create_db("sqlite://")
    ingest(engine, hand_data)
    facts = load_facts(engine)
    with pytest.raises(ValueError, match="window"):
        build_report(*facts, date(2025, 1, 10), date(2025, 1, 1))
    with pytest.raises(ValueError, match="snapshot"):
        build_report(*facts, date(2025, 1, 1), date(2026, 1, 1))


def test_products_with_same_display_name_keep_separate_skus(hand_data):
    hand_data["medicines"].append({**hand_data["medicines"][0], "id": 2, "sku": "SYN-002"})
    hand_data["batches"].append(
        {**hand_data["batches"][0], "id": 2, "medicine_id": 2, "batch_number": "SYN-B002"}
    )
    hand_data["sales_items"].append(
        {**hand_data["sales_items"][0], "id": 2, "batch_id": 2, "quantity": 5}
    )
    hand_data["inventory"].append(
        {"batch_id": 2, "quantity": 95, "snapshot_date": date(2025, 12, 31)}
    )
    engine = create_db("sqlite://")
    ingest(engine, hand_data)
    report = build_report(*load_facts(engine), date(2025, 1, 1), date(2025, 1, 10))
    assert report["invoices"] == 1
    assert report["stock_units"] == 185
    assert len(report["products"]) == 2
    assert report["products"]["units"].tolist() == [10, 5]
    assert report["products"]["sku"].tolist() == ["SYN-001", "SYN-002"]
