"""One row per sale line and one per batch: no fan-out inventory joins."""

from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

SALES_FACT_SQL = """
SELECT si.id, si.sale_id, s.sale_date, si.batch_id, si.quantity, si.unit_price,
       b.unit_cost, m.name AS medicine, m.sku, c.name AS category, w.region,
       w.name AS warehouse
FROM sales_items si JOIN sales s ON s.id=si.sale_id
JOIN batches b ON b.id=si.batch_id JOIN medicines m ON m.id=b.medicine_id
JOIN categories c ON c.id=m.category_id JOIN warehouses w ON w.id=s.warehouse_id
"""
BATCH_FACT_SQL = """
SELECT b.id AS batch_id, b.batch_number, b.received_date, b.expiry_date,
       b.received_quantity, b.unit_cost, m.name AS medicine, m.sku,
       c.name AS category, w.region, w.name AS warehouse, i.snapshot_date
FROM batches b JOIN medicines m ON m.id=b.medicine_id
JOIN categories c ON c.id=m.category_id JOIN warehouses w ON w.id=b.warehouse_id
JOIN inventory i ON i.batch_id=b.id
"""


def load_facts(engine: Engine) -> tuple[pd.DataFrame, pd.DataFrame]:
    # A single repeatable-read snapshot prevents mixing two ingestion generations.
    with engine.connect() as conn:
        if engine.dialect.name == "postgresql":
            conn = conn.execution_options(isolation_level="REPEATABLE READ")
        with conn.begin():
            return facts_from_connection(conn)


def facts_from_connection(conn) -> tuple[pd.DataFrame, pd.DataFrame]:
    sales = pd.read_sql(text(SALES_FACT_SQL), conn, coerce_float=False)
    batches = pd.read_sql(text(BATCH_FACT_SQL), conn, coerce_float=False)
    for frame in (sales, batches):
        for column in frame.columns:
            if column.endswith("_date"):
                frame[column] = pd.to_datetime(frame[column])
        for column in ("unit_price", "unit_cost"):
            if column in frame:
                frame[column + "_cents"] = frame[column].map(
                    lambda value: int((Decimal(str(value)) * 100).quantize(Decimal("1")))
                )
    return sales, batches


def build_report(
    sales: pd.DataFrame,
    batches: pd.DataFrame,
    start: date,
    end: date,
    regions: list[str] | None = None,
    categories: list[str] | None = None,
    risk_days: int = 90,
) -> dict:
    if start > end or risk_days < 0:
        raise ValueError("Invalid reporting window")
    if not batches.empty and pd.Timestamp(end) > batches["snapshot_date"].min():
        raise ValueError("Reporting date exceeds the synthetic inventory snapshot")
    sales, batches = sales.copy(), batches.copy()
    for column, selected in (("region", regions), ("category", categories)):
        if selected is not None:
            sales = sales[sales[column].isin(selected)].copy()
            batches = batches[batches[column].isin(selected)].copy()
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    history = sales[sales.sale_date <= hi]
    period = history[history.sale_date >= lo].copy()
    period["revenue_cents"] = period.quantity * period.unit_price_cents
    period["cogs_cents"] = period.quantity * period.unit_cost_cents
    stock = batches[batches.received_date <= hi].copy()
    sold = history.groupby("batch_id").quantity.sum()
    stock["stock_units"] = stock.received_quantity - stock.batch_id.map(sold).fillna(0).astype(int)
    if (stock.stock_units < 0).any():
        raise ValueError("Negative reconstructed inventory")
    stock["stock_value"] = stock.stock_units * stock.unit_cost_cents / 100
    stock["days_to_expiry"] = (stock.expiry_date - hi).dt.days
    stock["status"] = stock.days_to_expiry.map(
        lambda days: "Expired" if days < 0 else ("Near expiry" if days <= risk_days else "Healthy")
    )
    risk = stock[(stock.stock_units > 0) & (stock.days_to_expiry <= risk_days)].copy()
    # Integrate end-of-day inventory: each receipt/sale contributes for the days it remains.
    days = (end - start).days + 1
    receipt_days = (hi - stock.received_date.clip(lower=lo)).dt.days + 1
    sale_days = (hi - history.sale_date.clip(lower=lo)).dt.days + 1
    inventory_cent_days = int(
        (stock.received_quantity * stock.unit_cost_cents * receipt_days).sum()
    )
    inventory_cent_days -= int((history.quantity * history.unit_cost_cents * sale_days).sum())
    average = inventory_cent_days / days / 100
    if average < 0:
        raise ValueError("Negative average inventory")

    def breakdown(column: str | list[str]) -> pd.DataFrame:
        result = period.groupby(column, as_index=False).agg(
            revenue=("revenue_cents", "sum"), units=("quantity", "sum")
        )
        result["revenue"] = result.revenue / 100
        return result.sort_values("revenue", ascending=False)

    monthly = (
        period.assign(month=period.sale_date.dt.to_period("M").astype(str))
        .groupby("month")
        .agg(revenue=("revenue_cents", "sum"), units=("quantity", "sum"))
    )
    monthly = monthly.reindex(pd.period_range(start, end, freq="M").astype(str), fill_value=0)
    monthly["revenue"] = monthly.revenue / 100
    monthly.index.name = "month"
    cents = int(period.revenue_cents.sum())
    risk_cents = int((risk.stock_units * risk.unit_cost_cents).sum())
    return {
        "revenue": Decimal(cents) / 100,
        "units": int(period.quantity.sum()),
        "invoices": int(period.sale_id.nunique()),
        "stock_units": int(stock.stock_units.sum()),
        "stock_value": Decimal(int((stock.stock_units * stock.unit_cost_cents).sum())) / 100,
        "risk_value": Decimal(risk_cents) / 100,
        "expired_units": int(stock.loc[stock.days_to_expiry < 0, "stock_units"].sum()),
        "near_expiry_units": int(
            stock.loc[stock.days_to_expiry.between(0, risk_days), "stock_units"].sum()
        ),
        "average_inventory": average,
        "turnover": float(period.cogs_cents.sum()) / 100 / average if average > 0 else None,
        "monthly": monthly.reset_index(),
        "categories": breakdown("category"),
        "regions": breakdown("region"),
        "products": breakdown(["sku", "medicine"]).sort_values(
            ["units", "sku"], ascending=[False, True]
        ),
        "stock": stock,
        "risk": risk.sort_values(["days_to_expiry", "stock_value"], ascending=[True, False]),
        "sales": period,
        "risk_cutoff": end + timedelta(days=risk_days),
    }
