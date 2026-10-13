from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from pharma_suite.db import create_db, ingest
from pharma_suite.quality.demo import demo, expected_manifest, make_bundle
from pharma_suite.quality.engine import evaluate
from pharma_suite.quality.models import QualityConfig
from pharma_suite.quality.schema import audit, issues, records, runs
from pharma_suite.quality.store import (
    approve,
    correct_record,
    set_issue_status,
    stage,
    validate_dataset,
)
from pharma_suite.schema import tables


def test_clean_and_exact_fault_manifest():
    clean = evaluate(demo("demo-clean"))
    assert clean.overall_score == 100
    assert clean.findings == []
    corrupted = evaluate(demo("demo-corrupted"))
    actual = {(f.rule_id, f.entity, f.record_ref, f.field) for f in corrupted.findings}
    expected = {
        (f["rule_id"], f["entity"], f["record_ref"], f["field"])
        for f in expected_manifest()["findings"]
    }
    assert actual == expected
    assert corrupted.failed_records > 0
    assert corrupted.passed_records + corrupted.failed_records == corrupted.total_records


def test_scores_use_check_denominators_and_weights(hand_data):
    bundle = make_bundle(hand_data, "fixture")
    bundle.data["medicines"][0]["manufacturer"] = None
    report = evaluate(bundle)
    assert report.dimensions["completeness"]["failed"] == 1
    eligible = report.dimensions["completeness"]["eligible"]
    assert report.dimensions["completeness"]["score"] == pytest.approx(
        100 * (eligible - 1) / eligible
    )
    config = QualityConfig(
        weights={name: int(name == "completeness") for name in report.dimensions}
    )
    weighted = evaluate(bundle, config)
    assert weighted.overall_score == pytest.approx(report.dimensions["completeness"]["score"])
    assert weighted.failed_records == 1
    with pytest.raises(ValueError):
        QualityConfig(weights={name: 0 for name in report.dimensions})


@pytest.mark.parametrize(
    "field,value,rule",
    [
        ("manufacturer", None, "CMP001"),
        ("name", "", "CMP001"),
        ("list_price", "-1", "VAL003"),
        ("category_id", 999, "REF001"),
    ],
)
def test_medicine_rules(hand_data, field, value, rule):
    bundle = make_bundle(hand_data, "fixture")
    bundle.data["medicines"][0][field] = value
    assert any(f.rule_id == rule and f.field == field for f in evaluate(bundle).findings)


@pytest.mark.parametrize(
    "expiry,sellable,expected",
    [
        ("2025-01-01", False, False),
        ("2025-01-01", True, True),
        ("2025-12-31", True, False),
    ],
)
def test_expired_inventory_is_legitimate_until_marked_sellable(
    hand_data, expiry, sellable, expected
):
    bundle = make_bundle(hand_data, "fixture")
    bundle.data["batches"][0]["expiry_date"] = expiry
    bundle.data["inventory"][0]["is_sellable"] = sellable
    findings = evaluate(bundle).findings
    assert any(f.rule_id == "CON010" for f in findings) is expected


def test_sale_dates_and_chronological_oversell(hand_data):
    bundle = make_bundle(hand_data, "fixture")
    bundle.data["sales"][0]["sale_date"] = "2024-01-01"
    ids = {f.rule_id for f in evaluate(bundle).findings}
    assert {"CON003", "CON004"} <= ids
    bundle = make_bundle(hand_data, "fixture")
    bundle.data["sales_items"][0]["quantity"] = 101
    bundle.data["sales_items"][0]["line_total"] = "1515.00"
    bundle.data["sales"][0]["invoice_total"] = "1515.00"
    assert any(f.rule_id == "CON012" for f in evaluate(bundle).findings)


def test_uniqueness_marks_both_copies_and_malformed_dates_do_not_crash(hand_data):
    bundle = make_bundle(hand_data, "fixture")
    bundle.data["medicines"].append(deepcopy(bundle.data["medicines"][0]))
    duplicate = [f for f in evaluate(bundle).findings if f.rule_id == "UNI001"]
    assert len(duplicate) == 2
    bundle.data["sales"][0]["sale_date"] = "2025-99-99"
    assert any(f.rule_id == "VAL001" for f in evaluate(bundle).findings)


def test_timeliness_uses_explicit_clock(hand_data):
    bundle = make_bundle(hand_data, "fixture")
    report = evaluate(bundle, reference=datetime(2026, 1, 5, tzinfo=timezone.utc))
    assert {"TIM001", "TIM002"} <= {f.rule_id for f in report.findings}


def test_issue_lifecycle_quarantine_and_revalidation(tmp_path, hand_data):
    engine = create_db(f"sqlite:///{tmp_path}/quality.db")
    bundle = make_bundle(hand_data, "fixture")
    bundle.data["medicines"][0]["name"] = ""
    version = stage(engine, bundle)
    first = validate_dataset(engine, "fixture")
    second = validate_dataset(engine, "fixture")
    assert first.failed_records == second.failed_records == 1
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(issues)) == 1
        issue_id = conn.scalar(select(issues.c.id))
        assert conn.scalar(select(func.count()).select_from(runs)) == 2
        assert conn.scalar(select(records.c.quarantined).where(records.c.entity == "medicines"))
    set_issue_status(engine, issue_id, "acknowledged", "qa-reviewer", "Confirmed missing label")
    with pytest.raises(ValueError, match="findings"):
        approve(engine, "fixture", version, "qa-reviewer", "Attempt blocked")
    version = correct_record(
        engine,
        "fixture",
        "medicines",
        "medicines:1",
        {"name": "SYN-A 10mg"},
        "qa-reviewer",
        "Restored from synthetic manifest",
        version,
    )
    with pytest.raises(ValueError, match="revision"):
        correct_record(
            engine,
            "fixture",
            "medicines",
            "medicines:1",
            {"name": "wrong"},
            "qa-reviewer",
            "Stale edit",
            version - 1,
        )
    third = validate_dataset(engine, "fixture")
    assert third.findings == []
    with engine.connect() as conn:
        assert conn.scalar(select(issues.c.status)) == "resolved"
        assert conn.scalar(select(func.count()).select_from(audit)) >= 4
    assert (
        approve(engine, "fixture", version, "qa-reviewer", "Approved verified correction")[
            "medicines"
        ]
        == 1
    )
    assert (
        approve(engine, "fixture", version, "qa-reviewer", "Repeat approved load")["medicines"] == 1
    )


def test_approved_load_never_overwrites_transactions_or_deletes_rows(tmp_path, hand_data):
    engine = create_db(f"sqlite:///{tmp_path}/quality.db")
    ingest(engine, hand_data)
    bundle = make_bundle(hand_data, "fixture")
    bundle.data["medicines"][0]["list_price"] = "16.00"
    version = stage(engine, bundle)
    assert not validate_dataset(engine, "fixture").findings
    with pytest.raises(ValueError, match="conflict"):
        approve(engine, "fixture", version, "qa-reviewer", "Reviewed source")
    with engine.connect() as conn:
        assert conn.scalar(select(tables["medicines"].c.list_price)) == Decimal("15.00")
        assert conn.scalar(select(func.count()).select_from(tables["sales"])) == 1
    with pytest.raises(ValueError, match="notes"):
        set_issue_status(engine, 999, "resolved", "qa-reviewer", "")


@pytest.mark.parametrize(
    "entity,field,value,rule",
    [
        ("batches", "batch_number", "lower-case", "VAL006"),
        ("batches", "received_date", "2024-01-01", "CON002"),
        ("batches", "expiry_date", "2025-01-05", "CON005"),
        ("inventory", "quantity", 1.5, "VAL002"),
        ("inventory", "is_sellable", "true", "VAL008"),
        ("inventory", "snapshot_date", "2025-12-30", "CON013"),
        ("distributors", "region", "South", "CON014"),
        ("warehouses", "region", "Central", "VAL007"),
        ("medicines", "category_id", "1", "VAL004"),
        ("medicines", "list_price", "NaN", "VAL003"),
        ("sales_items", "medicine_id", 999, "CON007"),
        ("sales_items", "warehouse_id", 999, "CON006"),
        ("sales_items", "unit_price", "20.00", "VAL009"),
    ],
)
def test_remaining_individual_rules(hand_data, entity, field, value, rule):
    bundle = make_bundle(hand_data, "fixture")
    bundle.data[entity][0][field] = value
    assert rule in {f.rule_id for f in evaluate(bundle).findings}


@pytest.mark.parametrize(
    "entity,rule", [("categories", "CMP002"), ("inventory", "CON016"), ("sales_items", "CON015")]
)
def test_missing_entity_is_not_vacuously_clean(hand_data, entity, rule):
    bundle = make_bundle(hand_data, "fixture")
    bundle.data[entity] = []
    report = evaluate(bundle)
    assert rule in {f.rule_id for f in report.findings}
    assert report.overall_score < 100


def test_global_batch_namespace_matches_production(hand_data):
    bundle = make_bundle(hand_data, "fixture")
    bundle.data["batches"].append({**bundle.data["batches"][0], "id": 2})
    assert len([f for f in evaluate(bundle).findings if f.rule_id == "UNI003"]) == 2


def test_false_positive_review_does_not_bypass_failed_data(tmp_path, hand_data):
    engine = create_db(f"sqlite:///{tmp_path}/quality.db")
    bundle = make_bundle(hand_data, "fixture")
    bundle.data["medicines"][0]["name"] = ""
    stage(engine, bundle)
    validate_dataset(engine, "fixture")
    with engine.connect() as conn:
        issue_id = conn.scalar(select(issues.c.id))
    set_issue_status(engine, issue_id, "false_positive", "reviewer", "Flagged for investigation")
    assert validate_dataset(engine, "fixture").failed_records == 1
    with pytest.raises(ValueError, match="findings"):
        approve(engine, "fixture", 1, "reviewer", "Cannot bypass data failure")


def test_explicit_tombstone_preserves_duplicate_audit(tmp_path, hand_data):
    engine = create_db(f"sqlite:///{tmp_path}/quality.db")
    bundle = make_bundle(hand_data, "fixture")
    bundle.data["medicines"].append(deepcopy(bundle.data["medicines"][0]))
    stage(engine, bundle)
    assert validate_dataset(engine, "fixture").failed_records == 2
    correct_record(
        engine,
        "fixture",
        "medicines",
        "medicines:2",
        {},
        "reviewer",
        "Rejected duplicate",
        1,
        delete=True,
    )
    assert not validate_dataset(engine, "fixture").findings
    with engine.connect() as conn:
        assert (
            conn.scalar(
                select(func.count()).select_from(records).where(records.c.is_deleted.is_(True))
            )
            == 1
        )
        assert (
            conn.scalar(
                select(func.count()).select_from(audit).where(audit.c.action == "record_tombstone")
            )
            == 1
        )
