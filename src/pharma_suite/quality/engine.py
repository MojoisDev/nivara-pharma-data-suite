"""Pure validation and scoring over permissive staging records."""

import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from pharma_suite.quality.models import DIMENSIONS, Bundle, Finding, QualityConfig, Report
from pharma_suite.quality.rules import BUSINESS_KEYS, CATALOG, FOREIGN_KEYS, REQUIRED


def missing(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def parse_date(value) -> date | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def number(value) -> Decimal | None:
    if isinstance(value, bool) or isinstance(value, (list, dict)):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def integer(value) -> bool:
    return type(value) is int


def evaluate(
    bundle: Bundle,
    config: QualityConfig | None = None,
    reference: datetime | None = None,
    refs: dict[str, list[str]] | None = None,
) -> Report:
    config = config or QualityConfig()
    reference = reference or bundle.reference_at
    if reference.tzinfo is None:
        raise ValueError("Assessment clock requires a timezone")
    reference = reference.astimezone(timezone.utc)
    findings = []
    stats = {rid: {"eligible": 0, "failed": 0, "not_applicable": 0} for rid in CATALOG}
    failed_rows = set()
    rows = {
        entity: [
            (refs[entity][i] if refs else f"{entity}:{i + 1}", row)
            for i, row in enumerate(bundle.data.get(entity, []))
        ]
        for entity in REQUIRED
    }
    # Only unambiguous, correctly typed IDs support dependent checks.
    indexes = {}
    id_sets = {}
    for entity, entries in rows.items():
        key = "batch_id" if entity == "inventory" else "id"
        groups = defaultdict(list)
        for _ref, row in entries:
            if integer(row.get(key)) and row[key] > 0:
                groups[row[key]].append(row)
        indexes[entity] = {key: group[0] for key, group in groups.items() if len(group) == 1}
        id_sets[entity] = set(groups)

    def check(rid, entity, ref, row, field, ok, eligible=True):
        if not eligible:
            stats[rid]["not_applicable"] += 1
            return
        stats[rid]["eligible"] += 1
        if ok:
            return
        stats[rid]["failed"] += 1
        rule = CATALOG[rid]
        mid = row.get("medicine_id") if isinstance(row, dict) else None
        if entity == "medicines":
            mid = row.get("id")
        bid = row.get("batch_id") if isinstance(row, dict) else None
        if entity == "batches":
            bid = row.get("id")
        findings.append(
            Finding(
                rule_id=rid,
                rule_version=rule.version,
                dimension=rule.dimension,
                severity=rule.severity,
                entity=entity,
                record_ref=ref,
                field=field,
                description=f"{rule.description}: {field}",
                remediation=rule.remediation,
                medicine_ref=str(mid) if mid is not None else None,
                batch_ref=str(bid) if bid is not None else None,
            )
        )
        if entity in REQUIRED:
            failed_rows.add((entity, ref))

    snapshot = parse_date(bundle.snapshot_date)
    metadata = bundle.model_dump(exclude={"data"}, mode="json")
    for field in ("snapshot_date", "source_received_at", "feed_date"):
        check("CMP001", "__metadata__", "metadata", metadata, field, not missing(metadata[field]))
    check(
        "VAL001",
        "__metadata__",
        "metadata",
        metadata,
        "snapshot_date",
        snapshot is not None,
        not missing(bundle.snapshot_date),
    )
    for entity, entries in rows.items():
        check("CMP002", "__dataset__", entity, {}, entity, bool(entries))
        for ref, row in entries:
            for field in REQUIRED[entity]:
                check("CMP001", entity, ref, row, field, not missing(row.get(field)))
            for field, value in row.items():
                if missing(value):
                    continue
                if field.endswith("_date"):
                    check("VAL001", entity, ref, row, field, parse_date(value) is not None)
                elif field in {
                    "id",
                    "batch_id",
                    "medicine_id",
                    "category_id",
                    "warehouse_id",
                    "sale_id",
                    "distributor_id",
                }:
                    check("VAL004", entity, ref, row, field, integer(value) and value > 0)
                elif field in {"quantity", "received_quantity"}:
                    minimum = 0 if entity == "inventory" else 1
                    check(
                        "VAL002",
                        entity,
                        ref,
                        row,
                        field,
                        integer(value) and minimum <= value <= config.max_quantity,
                    )
                elif field in {"unit_price", "list_price", "unit_cost"}:
                    val = number(value)
                    check(
                        "VAL003",
                        entity,
                        ref,
                        row,
                        field,
                        val is not None
                        and 0 < val <= Decimal(str(config.max_price))
                        and val == val.quantize(Decimal(".01")),
                    )
                elif field == "contact_email":
                    check(
                        "VAL005",
                        entity,
                        ref,
                        row,
                        field,
                        isinstance(value, str)
                        and bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value)),
                    )
                elif field == "batch_number":
                    check(
                        "VAL006",
                        entity,
                        ref,
                        row,
                        field,
                        isinstance(value, str)
                        and bool(re.fullmatch(r"[A-Z0-9][A-Z0-9-]{2,29}", value)),
                    )
                elif field == "region":
                    check(
                        "VAL007",
                        entity,
                        ref,
                        row,
                        field,
                        value in ("North", "South", "East", "West"),
                    )
                elif field == "is_sellable":
                    check("VAL008", entity, ref, row, field, type(value) is bool)
            for field, target in FOREIGN_KEYS.get(entity, {}).items():
                value = row.get(field)
                check(
                    "REF001",
                    entity,
                    ref,
                    row,
                    field,
                    integer(value) and value in id_sets[target],
                    not missing(value),
                )
        for rid, fields in [
            ("UNI001", ("batch_id",) if entity == "inventory" else ("id",)),
            ("UNI002", BUSINESS_KEYS.get(entity, ())),
            ("UNI003", ("batch_number",) if entity == "batches" else ()),
        ]:
            if not fields:
                continue
            keys = [
                tuple(str(row.get(field)) for field in fields)
                for _, row in entries
                if all(not missing(row.get(field)) for field in fields)
            ]
            counts = Counter(keys)
            for ref, row in entries:
                key = tuple(str(row.get(field)) for field in fields)
                check(
                    rid,
                    entity,
                    ref,
                    row,
                    "+".join(fields),
                    counts[key] == 1,
                    all(not missing(row.get(field)) for field in fields),
                )

    for ref, batch in rows["batches"]:
        manufacture, received, expiry = (
            parse_date(batch.get(f)) for f in ("manufacture_date", "received_date", "expiry_date")
        )
        check(
            "CON001",
            "batches",
            ref,
            batch,
            "expiry_date",
            bool(manufacture and expiry and expiry > manufacture),
            manufacture is not None and expiry is not None,
        )
        check(
            "CON002",
            "batches",
            ref,
            batch,
            "received_date",
            bool(manufacture and received and expiry and manufacture <= received <= expiry),
            all(v is not None for v in (manufacture, received, expiry)),
        )
        check(
            "CON013",
            "batches",
            ref,
            batch,
            "received_date",
            bool(received and snapshot and received <= snapshot),
            received is not None and snapshot is not None,
        )
        bid = batch.get("id")
        check(
            "CON016",
            "batches",
            ref,
            batch,
            "inventory",
            integer(bid) and bid in id_sets["inventory"],
            integer(bid),
        )

    items_by_sale = defaultdict(list)
    items_by_batch = defaultdict(list)
    for ref, item in rows["sales_items"]:
        if integer(item.get("sale_id")):
            items_by_sale[item["sale_id"]].append((ref, item))
        if integer(item.get("batch_id")):
            items_by_batch[item["batch_id"]].append((ref, item))
        sale = indexes["sales"].get(item.get("sale_id")) if integer(item.get("sale_id")) else None
        batch = (
            indexes["batches"].get(item.get("batch_id")) if integer(item.get("batch_id")) else None
        )
        q, price, total = (number(item.get(f)) for f in ("quantity", "unit_price", "line_total"))
        valid_amount = (
            integer(item.get("quantity"))
            and q is not None
            and 0 < q <= config.max_quantity
            and price is not None
            and 0 < price <= Decimal(str(config.max_price))
        )
        check(
            "CON008",
            "sales_items",
            ref,
            item,
            "line_total",
            valid_amount and total == q * price,
            valid_amount and not missing(item.get("line_total")),
        )
        if batch and sale:
            sale_date = parse_date(sale.get("sale_date"))
            for rid, field, operator in [
                ("CON003", "manufacture_date", "ge"),
                ("CON004", "received_date", "ge"),
                ("CON005", "expiry_date", "le"),
            ]:
                target = parse_date(batch.get(field))
                okay = (
                    sale_date is not None
                    and target is not None
                    and (sale_date >= target if operator == "ge" else sale_date <= target)
                )
                check(
                    rid,
                    "sales_items",
                    ref,
                    item,
                    "sale_date",
                    okay,
                    sale_date is not None and target is not None,
                )
            check(
                "CON006",
                "sales_items",
                ref,
                item,
                "warehouse_id",
                item.get("warehouse_id") == sale.get("warehouse_id") == batch.get("warehouse_id"),
                all(integer(r.get("warehouse_id")) for r in (item, sale, batch)),
            )
            check(
                "CON007",
                "sales_items",
                ref,
                item,
                "medicine_id",
                item.get("medicine_id") == batch.get("medicine_id"),
                integer(item.get("medicine_id")) and integer(batch.get("medicine_id")),
            )
            medicine = (
                indexes["medicines"].get(batch.get("medicine_id"))
                if integer(batch.get("medicine_id"))
                else None
            )
            list_price = number(medicine.get("list_price")) if medicine else None
            check(
                "VAL009",
                "sales_items",
                ref,
                item,
                "unit_price",
                bool(
                    price
                    and list_price
                    and price <= list_price * Decimal(str(config.max_price_to_list_ratio))
                ),
                price is not None and price > 0 and list_price is not None and list_price > 0,
            )

    for ref, sale in rows["sales"]:
        lines = items_by_sale.get(sale.get("id"), []) if integer(sale.get("id")) else []
        check("CON015", "sales", ref, sale, "sales_items", bool(lines), integer(sale.get("id")))
        amounts = [
            (number(item.get("quantity")), number(item.get("unit_price"))) for _, item in lines
        ]
        valid_lines = bool(lines) and all(
            q is not None
            and 0 < q <= config.max_quantity
            and p is not None
            and 0 < p <= Decimal(str(config.max_price))
            for q, p in amounts
        )
        total = number(sale.get("invoice_total"))
        check(
            "CON009",
            "sales",
            ref,
            sale,
            "invoice_total",
            valid_lines and total == sum(q * p for q, p in amounts),
            valid_lines and not missing(sale.get("invoice_total")),
        )
        sale_date = parse_date(sale.get("sale_date"))
        check(
            "CON013",
            "sales",
            ref,
            sale,
            "sale_date",
            bool(sale_date and snapshot and sale_date <= snapshot),
            sale_date is not None and snapshot is not None,
        )
        customer = (
            indexes["distributors"].get(sale.get("distributor_id"))
            if integer(sale.get("distributor_id"))
            else None
        )
        warehouse = (
            indexes["warehouses"].get(sale.get("warehouse_id"))
            if integer(sale.get("warehouse_id"))
            else None
        )
        check(
            "CON014",
            "sales",
            ref,
            sale,
            "region",
            bool(customer and warehouse and customer.get("region") == warehouse.get("region")),
            customer is not None and warehouse is not None,
        )

    # Chronological oversell is checked per line against a single batch's one receipt event.
    batch_totals = {}
    for bid, entries in items_by_batch.items():
        batch = indexes["batches"].get(bid)
        if not batch:
            continue
        history = []
        for ref, item in entries:
            sale = (
                indexes["sales"].get(item.get("sale_id")) if integer(item.get("sale_id")) else None
            )
            sale_date = parse_date(sale.get("sale_date")) if sale else None
            if sale_date is not None and integer(item.get("quantity")) and item["quantity"] > 0:
                history.append((sale_date, ref, item))
        if len(history) != len(entries):
            for ref, item in entries:
                check("CON012", "sales_items", ref, item, "quantity", True, False)
            continue
        received = parse_date(batch.get("received_date"))
        received_quantity = batch.get("received_quantity")
        if received is None or not integer(received_quantity) or received_quantity <= 0:
            continue
        sold = 0
        for _sale_date, ref, item in sorted(history, key=lambda x: (x[0], x[1])):
            sold += item["quantity"]
            # Before-receipt sales are CON004; separate oversell concerns total capacity.
            check("CON012", "sales_items", ref, item, "quantity", sold <= received_quantity)
        if snapshot is not None:
            batch_totals[bid] = sum(item["quantity"] for d, _, item in history if d <= snapshot)

    for ref, stock in rows["inventory"]:
        bid = stock.get("batch_id")
        batch = indexes["batches"].get(bid) if integer(bid) else None
        expiry = parse_date(batch.get("expiry_date")) if batch else None
        stock_date = parse_date(stock.get("snapshot_date"))
        check(
            "CON013",
            "inventory",
            ref,
            stock,
            "snapshot_date",
            stock_date == snapshot,
            stock_date is not None and snapshot is not None,
        )
        qty = stock.get("quantity")
        check(
            "CON010",
            "inventory",
            ref,
            stock,
            "is_sellable",
            not (expiry < stock_date and qty > 0 and stock.get("is_sellable") is True)
            if expiry and stock_date and integer(qty)
            else True,
            expiry is not None
            and stock_date is not None
            and integer(qty)
            and type(stock.get("is_sellable")) is bool,
        )
        receipt = batch.get("received_quantity") if batch else None
        eligible = (
            batch is not None
            and integer(receipt)
            and integer(qty)
            and stock_date == snapshot
            and parse_date(batch.get("received_date")) is not None
            and parse_date(batch.get("received_date")) <= snapshot
            and (bid in batch_totals or bid not in items_by_batch)
        )
        check(
            "CON011",
            "inventory",
            ref,
            stock,
            "quantity",
            eligible and qty == receipt - batch_totals.get(bid, 0),
            eligible,
        )

    try:
        imported = datetime.fromisoformat(bundle.source_received_at or "")
        import_ok = (
            imported.tzinfo is not None
            and 0 <= (reference - imported).total_seconds() / 3600 <= config.max_import_age_hours
        )
    except (ValueError, TypeError):
        import_ok = False
    check("TIM001", "__metadata__", "metadata", metadata, "source_received_at", import_ok)
    feed_date = parse_date(bundle.feed_date)
    check(
        "TIM002",
        "__metadata__",
        "metadata",
        metadata,
        "feed_date",
        feed_date is not None
        and 0 <= (reference.date() - feed_date).days <= config.max_feed_lag_days,
    )
    dimensions = {}
    for dimension in DIMENSIONS:
        selected = [stats[rid] for rid, rule in CATALOG.items() if rule.dimension == dimension]
        eligible = sum(row["eligible"] for row in selected)
        failed = sum(row["failed"] for row in selected)
        dimensions[dimension] = {
            "eligible": eligible,
            "failed": failed,
            "not_applicable": sum(row["not_applicable"] for row in selected),
            "score": 100 * (eligible - failed) / eligible if eligible else None,
        }
    weight = sum(
        config.weights[name] for name, row in dimensions.items() if row["score"] is not None
    )
    overall = (
        sum(
            config.weights[name] * row["score"]
            for name, row in dimensions.items()
            if row["score"] is not None
        )
        / weight
        if weight
        else None
    )
    total_records = sum(len(entries) for entries in rows.values())
    return Report(
        dataset=bundle.name,
        reference_at=reference,
        dimensions=dimensions,
        rules=stats,
        overall_score=overall,
        total_records=total_records,
        failed_records=len(failed_rows),
        passed_records=total_records - len(failed_rows),
        severity_counts=dict(Counter(f.severity for f in findings)),
        findings=findings,
    )
