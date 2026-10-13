"""Deterministic fictional wholesale receipts, FEFO sales, and closing stock."""

import calendar
import random
from datetime import date, timedelta
from decimal import Decimal

SNAPSHOT = date(2025, 12, 31)
SEED = 20251011
TABLE_ORDER = (
    "categories",
    "medicines",
    "distributors",
    "warehouses",
    "batches",
    "inventory",
    "sales",
    "sales_items",
)
REGIONS = {"North": "Delhi", "South": "Chennai", "East": "Kolkata", "West": "Mumbai"}


def generate(seed: int = SEED) -> dict[str, list[dict]]:
    rng = random.Random(seed)
    data = {name: [] for name in TABLE_ORDER}
    category_names = [
        "Cardiology",
        "Anti-infectives",
        "Diabetes care",
        "Respiratory",
        "Gastrointestinal",
        "Pain management",
        "Dermatology",
        "Nutrition",
    ]
    data["categories"] = [{"id": i, "name": n} for i, n in enumerate(category_names, 1)]
    for i in range(1, 121):
        data["medicines"].append(
            {
                "id": i,
                "category_id": (i - 1) % 8 + 1,
                "name": f"SYN-{category_names[(i - 1) % 8].split()[0]} "
                f"{i:03} {rng.choice([5, 10, 20, 50])}mg",
                "sku": f"SYN-M{i:03}",
                "manufacturer": f"SYN Manufacturing Group {(i - 1) % 8 + 1}",
                "dosage_form": rng.choice(["Tablet", "Capsule", "Vial"]),
                "list_price": Decimal(rng.randint(40, 480)),
            }
        )
    for wid, (region, city) in enumerate(REGIONS.items(), 1):
        data["warehouses"].append(
            {"id": wid, "name": f"SYN {city} distribution hub", "region": region, "city": city}
        )
        for j in range(6):
            data["distributors"].append(
                {
                    "id": (wid - 1) * 6 + j + 1,
                    "name": f"SYN {region} distributor {j + 1:02}",
                    "region": region,
                    "city": city,
                    "contact_email": f"distributor{(wid - 1) * 6 + j + 1}@synthetic.example",
                }
            )
    pools = {}
    remaining = {}
    for medicine in data["medicines"]:
        for wid in range(1, 5):
            pool = []
            for year, month in [(2024, 1), (2024, 7), (2025, 1), (2025, 7)]:
                bid = len(data["batches"]) + 1
                received = date(year, month, 1)
                batch = {
                    "id": bid,
                    "medicine_id": medicine["id"],
                    "warehouse_id": wid,
                    "batch_number": f"SYN-B{bid:05}",
                    "received_date": received,
                    "manufacture_date": received - timedelta(days=45),
                    "expiry_date": received + timedelta(days=rng.choice([550, 730, 900])),
                    "unit_cost": (medicine["list_price"] * Decimal("0.58")).quantize(
                        Decimal(".01")
                    ),
                    "received_quantity": rng.randint(350, 600),
                }
                data["batches"].append(batch)
                remaining[bid] = batch["received_quantity"]
                pool.append(batch)
            pools[(medicine["id"], wid)] = sorted(pool, key=lambda b: (b["expiry_date"], b["id"]))
    for year in (2024, 2025):
        for month in range(1, 13):
            count = 320 + month * 5 + (year - 2024) * 30
            for _ in range(count):
                day = rng.randint(1, calendar.monthrange(year, month)[1])
                sale_date = date(year, month, day)
                wid = rng.choices([1, 2, 3, 4], weights=[25, 30, 18, 27])[0]
                data["sales"].append(
                    {
                        "id": len(data["sales"]) + 1,
                        "distributor_id": (wid - 1) * 6 + rng.randint(1, 6),
                        "warehouse_id": wid,
                        "sale_date": sale_date,
                        "invoice_number": f"SYN-I{len(data['sales']) + 1:06}",
                    }
                )
    # Process chronologically so a later invoice cannot consume earlier available stock.
    for sale in sorted(data["sales"], key=lambda s: (s["sale_date"], s["id"])):
        for mid in rng.sample(range(1, 121), rng.randint(2, 5)):
            requested = rng.randint(4, 24)
            for batch in pools[(mid, sale["warehouse_id"])]:
                if not batch["received_date"] <= sale["sale_date"] <= batch["expiry_date"]:
                    continue
                quantity = min(requested, remaining[batch["id"]])
                if quantity == 0:
                    continue
                price = (
                    data["medicines"][mid - 1]["list_price"]
                    * Decimal(rng.choice(["0.92", "0.95", "0.98", "1.00"]))
                ).quantize(Decimal(".01"))
                data["sales_items"].append(
                    {
                        "id": len(data["sales_items"]) + 1,
                        "sale_id": sale["id"],
                        "warehouse_id": sale["warehouse_id"],
                        "batch_id": batch["id"],
                        "quantity": quantity,
                        "unit_price": price,
                    }
                )
                remaining[batch["id"]] -= quantity
                requested -= quantity
                if requested == 0:
                    break
    data["inventory"] = [
        {
            "batch_id": b["id"],
            "quantity": remaining[b["id"]],
            "snapshot_date": SNAPSHOT,
            "is_sellable": b["expiry_date"] >= SNAPSHOT,
        }
        for b in data["batches"]
    ]
    validate(data)
    return data


def validate(data: dict[str, list[dict]]) -> None:
    """Reject inconsistent imports before any database write; DB enforces scalar/FK rules."""
    from pharma_suite.schema import tables

    if set(data) != set(TABLE_ORDER):
        raise ValueError("Dataset must contain exactly the eight foundation tables")
    indexes = {}
    for name in TABLE_ORDER:
        key = "batch_id" if name == "inventory" else "id"
        required_columns = {c.name for c in tables[name].c if not c.nullable}
        if any(
            not required_columns <= set(row) or set(row) - set(tables[name].c.keys())
            for row in data[name]
        ):
            raise ValueError(f"Invalid columns in {name}")
        indexes[name] = {row[key]: row for row in data[name]}
        if len(indexes[name]) != len(data[name]):
            raise ValueError(f"Duplicate primary key in {name}")
    for medicine in data["medicines"]:
        if medicine["category_id"] not in indexes["categories"]:
            raise ValueError("Unknown medicine category")
    for batch in data["batches"]:
        if (
            batch["medicine_id"] not in indexes["medicines"]
            or batch["warehouse_id"] not in indexes["warehouses"]
        ):
            raise ValueError("Unknown batch medicine or warehouse")
        if (
            batch["received_quantity"] <= 0
            or batch["unit_cost"] <= 0
            or not batch["manufacture_date"] <= batch["received_date"] <= batch["expiry_date"]
        ):
            raise ValueError("Invalid batch receipt")
    for sale in data["sales"]:
        distributor = indexes["distributors"].get(sale["distributor_id"])
        warehouse = indexes["warehouses"].get(sale["warehouse_id"])
        if not distributor or not warehouse or distributor["region"] != warehouse["region"]:
            raise ValueError("Unknown or cross-region distributor / warehouse")
    sold = {}
    invoice_batches = set()
    invoices = set()
    for item in data["sales_items"]:
        batch = indexes["batches"].get(item["batch_id"])
        sale = indexes["sales"].get(item["sale_id"])
        if not batch or not sale:
            raise ValueError("Unknown sale or batch")
        if (
            item["warehouse_id"] != batch["warehouse_id"]
            or item["warehouse_id"] != sale["warehouse_id"]
        ):
            raise ValueError("Sale and batch warehouses differ")
        if not batch["received_date"] <= sale["sale_date"] <= batch["expiry_date"]:
            raise ValueError("Sale outside receipt / expiry window")
        if item["quantity"] <= 0 or item["unit_price"] <= 0:
            raise ValueError("Invalid sale quantity or price")
        pair = (item["sale_id"], item["batch_id"])
        if pair in invoice_batches:
            raise ValueError("Duplicate invoice batch line")
        invoice_batches.add(pair)
        invoices.add(item["sale_id"])
        sold[item["batch_id"]] = sold.get(item["batch_id"], 0) + item["quantity"]
    if invoices != set(indexes["sales"]):
        raise ValueError("Empty sales invoice")
    if set(indexes["inventory"]) != set(indexes["batches"]):
        raise ValueError("Missing inventory snapshot batch")
    snapshots = {row["snapshot_date"] for row in data["inventory"]}
    if len(snapshots) != 1:
        raise ValueError("Inventory must share one snapshot date")
    snapshot = next(iter(snapshots))
    if any(b["received_date"] > snapshot for b in data["batches"]) or any(
        s["sale_date"] > snapshot for s in data["sales"]
    ):
        raise ValueError("Transactions after inventory snapshot")
    for stock in data["inventory"]:
        expected = indexes["batches"][stock["batch_id"]]["received_quantity"] - sold.get(
            stock["batch_id"], 0
        )
        if expected < 0 or stock["quantity"] != expected:
            raise ValueError("Inventory reconciliation failed")
