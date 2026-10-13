"""Portable relational model; PostgreSQL is the deployment target."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    UniqueConstraint,
)

metadata = MetaData()
money = Numeric(12, 2)
categories = Table(
    "categories",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(80), nullable=False, unique=True),
)
medicines = Table(
    "medicines",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("category_id", ForeignKey("categories.id"), nullable=False, index=True),
    Column("name", String(120), nullable=False),
    Column("sku", String(30), nullable=False, unique=True),
    Column("dosage_form", String(30), nullable=False),
    Column("manufacturer", String(120)),
    Column("list_price", money, nullable=False),
    CheckConstraint("list_price > 0"),
)


def location_table(name: str) -> Table:
    return Table(
        name,
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(100), nullable=False, unique=True),
        Column("region", String(20), nullable=False, index=True),
        Column("city", String(50), nullable=False),
        CheckConstraint("region IN ('North','South','East','West')"),
    )


distributors = location_table("distributors")
distributors.append_column(Column("contact_email", String(254)))
warehouses = location_table("warehouses")
batches = Table(
    "batches",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("medicine_id", ForeignKey("medicines.id"), nullable=False, index=True),
    Column("warehouse_id", ForeignKey("warehouses.id"), nullable=False, index=True),
    Column("batch_number", String(30), nullable=False, unique=True),
    Column("manufacture_date", Date, nullable=False),
    Column("received_date", Date, nullable=False),
    Column("expiry_date", Date, nullable=False, index=True),
    Column("unit_cost", money, nullable=False),
    Column("received_quantity", Integer, nullable=False),
    UniqueConstraint("id", "warehouse_id"),
    CheckConstraint("received_quantity > 0"),
    CheckConstraint("unit_cost > 0"),
    CheckConstraint("manufacture_date <= received_date AND received_date <= expiry_date"),
)
inventory = Table(
    "inventory",
    metadata,
    Column("batch_id", ForeignKey("batches.id"), primary_key=True),
    Column("quantity", Integer, nullable=False),
    Column("snapshot_date", Date, nullable=False),
    Column("is_sellable", Boolean),
    CheckConstraint("quantity >= 0"),
)
sales = Table(
    "sales",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("distributor_id", ForeignKey("distributors.id"), nullable=False, index=True),
    Column("warehouse_id", ForeignKey("warehouses.id"), nullable=False),
    Column("sale_date", Date, nullable=False, index=True),
    Column("invoice_number", String(30), nullable=False, unique=True),
    UniqueConstraint("id", "warehouse_id"),
)
sales_items = Table(
    "sales_items",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("sale_id", Integer, nullable=False),
    Column("warehouse_id", Integer, nullable=False),
    Column("batch_id", Integer, nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("unit_price", money, nullable=False),
    ForeignKeyConstraint(["sale_id", "warehouse_id"], ["sales.id", "sales.warehouse_id"]),
    ForeignKeyConstraint(["batch_id", "warehouse_id"], ["batches.id", "batches.warehouse_id"]),
    UniqueConstraint("sale_id", "batch_id"),
    CheckConstraint("quantity > 0"),
    CheckConstraint("unit_price > 0"),
)
Index("ix_items_batch_sale", sales_items.c.batch_id, sales_items.c.sale_id)
tables = {table.name: table for table in metadata.sorted_tables}
