"""Deterministic demos with an independently specified fault manifest."""

import json
from copy import deepcopy
from datetime import date
from decimal import Decimal
from functools import lru_cache

from pharma_suite.generate import generate
from pharma_suite.quality.models import Bundle


def make_bundle(data: dict, name: str) -> Bundle:
    raw = json.loads(json.dumps(data, default=str))
    batches = {r["id"]: r for r in raw["batches"]}
    totals = {}
    for medicine in raw["medicines"]:
        medicine.setdefault("manufacturer", f"SYN Manufacturing Group {medicine['category_id']}")
    for distributor in raw["distributors"]:
        distributor.setdefault("contact_email", f"distributor{distributor['id']}@synthetic.example")
    for stock in raw["inventory"]:
        batch = batches[stock["batch_id"]]
        stock.setdefault("is_sellable", batch["expiry_date"] >= stock["snapshot_date"])
    for item in raw["sales_items"]:
        item["medicine_id"] = batches[item["batch_id"]]["medicine_id"]
        item["line_total"] = str(Decimal(str(item["quantity"])) * Decimal(item["unit_price"]))
        totals[item["sale_id"]] = totals.get(item["sale_id"], Decimal(0)) + Decimal(
            item["line_total"]
        )
    for sale in raw["sales"]:
        sale["invoice_total"] = str(totals.get(sale["id"], Decimal(0)))
    return Bundle(
        name=name,
        reference_at="2026-01-01T12:00:00+00:00",
        source_received_at="2026-01-01T00:00:00+00:00",
        feed_date="2025-12-31",
        snapshot_date="2025-12-31",
        data=raw,
    )


@lru_cache(maxsize=1)
def _corrupted():
    bundle = make_bundle(generate(), "demo-corrupted")
    expected = []
    scenarios = []

    def expect(rule, entity, index, field):
        expected.append(
            {
                "rule_id": rule,
                "rule_version": "1.0",
                "entity": entity,
                "record_ref": f"{entity}:{index + 1}" if entity in bundle.data else "metadata",
                "field": field,
            }
        )

    med = bundle.data["medicines"]
    med.append(deepcopy(med[0]))
    for index in (0, len(med) - 1):
        expect("UNI001", "medicines", index, "id")
        expect("UNI002", "medicines", index, "sku")
    scenarios.append("Duplicate medicine: both original and appended copy are flagged")
    med[1]["manufacturer"] = None
    expect("CMP001", "medicines", 1, "manufacturer")
    med[2]["name"] = ""
    expect("CMP001", "medicines", 2, "name")
    med[3]["category_id"] = 99999
    expect("REF001", "medicines", 3, "category_id")
    med[4]["list_price"] = "-1.00"
    expect("VAL003", "medicines", 4, "list_price")
    scenarios += [
        "Missing manufacturer",
        "Missing medicine name",
        "Orphan category FK",
        "Impossible list price",
    ]
    stocks = bundle.data["inventory"]
    stocks[0]["quantity"] = -1
    expect("VAL002", "inventory", 0, "quantity")
    expect("CON011", "inventory", 0, "quantity")
    scenarios.append("Negative stock also contradicts closing reconciliation")
    used_batches = {row["batch_id"] for row in bundle.data["sales_items"]}
    unused_index = next(
        i for i, b in enumerate(bundle.data["batches"]) if b["id"] not in used_batches
    )
    batch = bundle.data["batches"][unused_index]
    batch["expiry_date"] = batch["manufacture_date"]
    stocks[unused_index]["is_sellable"] = False
    expect("CON001", "batches", unused_index, "expiry_date")
    expect("CON002", "batches", unused_index, "received_date")
    scenarios.append(
        "Unused batch expires on manufacture date; correct unavailable flag avoids an "
        "extra availability fault"
    )
    malformed_index = next(
        i
        for i, b in enumerate(bundle.data["batches"])
        if b["id"] not in used_batches and i != unused_index
    )
    bundle.data["batches"][malformed_index]["received_date"] = "2025-99-40"
    expect("VAL001", "batches", malformed_index, "received_date")
    scenarios.append("Malformed receipt date")
    bundle.data["sales_items"][0]["line_total"] = str(
        Decimal(bundle.data["sales_items"][0]["line_total"]) + 1
    )
    expect("CON008", "sales_items", 0, "line_total")
    scenarios.append(
        "Incorrect declared line amount; invoice checks use calculated amounts, not this "
        "faulty declaration"
    )
    bundle.data["sales"][1]["invoice_total"] = str(
        Decimal(bundle.data["sales"][1]["invoice_total"]) + 1
    )
    expect("CON009", "sales", 1, "invoice_total")
    scenarios.append("Incorrect declared invoice total")
    expired_index = next(
        i
        for i, b in enumerate(bundle.data["batches"])
        if date.fromisoformat(b["expiry_date"]) < date(2025, 12, 31)
        and stocks[i]["quantity"] > 0
        and i != unused_index
    )
    stocks[expired_index]["is_sellable"] = True
    expect("CON010", "inventory", expired_index, "is_sellable")
    scenarios.append("Legitimate expired held stock incorrectly marked sellable")
    bundle.data["distributors"][0]["contact_email"] = "broken-email"
    expect("VAL005", "distributors", 0, "contact_email")
    scenarios.append("Invalid synthetic contact email")
    bundle.source_received_at = "2025-12-28T00:00:00+00:00"
    bundle.feed_date = "2025-12-25"
    expect("TIM001", "__metadata__", 0, "source_received_at")
    expect("TIM002", "__metadata__", 0, "feed_date")
    scenarios += ["Stale import", "Delayed reporting feed"]
    return bundle, {
        "synthetic": True,
        "seed": 20251011,
        "reference_at": bundle.reference_at.isoformat(),
        "scenarios": scenarios,
        "expected_count": len(expected),
        "findings": expected,
    }


def demo(name: str) -> Bundle:
    if name == "demo-clean":
        return make_bundle(generate(), name)
    if name == "demo-corrupted":
        return _corrupted()[0].model_copy(deep=True)
    raise ValueError("Unknown built-in demo dataset")


def expected_manifest() -> dict:
    return deepcopy(_corrupted()[1])
