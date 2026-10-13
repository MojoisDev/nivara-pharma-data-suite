-- Phase 1 / schema v1. Synthetic data only. Generated from schema.py.
BEGIN;
CREATE TABLE IF NOT EXISTS categories (
	id SERIAL NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS distributors (
	id SERIAL NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	region VARCHAR(20) NOT NULL, 
	city VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (region IN ('North','South','East','West')), 
	UNIQUE (name)
);

CREATE INDEX IF NOT EXISTS ix_distributors_region ON distributors (region);

CREATE TABLE IF NOT EXISTS warehouses (
	id SERIAL NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	region VARCHAR(20) NOT NULL, 
	city VARCHAR(50) NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (region IN ('North','South','East','West')), 
	UNIQUE (name)
);

CREATE INDEX IF NOT EXISTS ix_warehouses_region ON warehouses (region);

CREATE TABLE IF NOT EXISTS medicines (
	id SERIAL NOT NULL, 
	category_id INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	sku VARCHAR(30) NOT NULL, 
	dosage_form VARCHAR(30) NOT NULL, 
	list_price NUMERIC(12, 2) NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (list_price > 0), 
	FOREIGN KEY(category_id) REFERENCES categories (id), 
	UNIQUE (sku)
);

CREATE INDEX IF NOT EXISTS ix_medicines_category_id ON medicines (category_id);

CREATE TABLE IF NOT EXISTS sales (
	id SERIAL NOT NULL, 
	distributor_id INTEGER NOT NULL, 
	warehouse_id INTEGER NOT NULL, 
	sale_date DATE NOT NULL, 
	invoice_number VARCHAR(30) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (id, warehouse_id), 
	FOREIGN KEY(distributor_id) REFERENCES distributors (id), 
	FOREIGN KEY(warehouse_id) REFERENCES warehouses (id), 
	UNIQUE (invoice_number)
);

CREATE INDEX IF NOT EXISTS ix_sales_distributor_id ON sales (distributor_id);

CREATE INDEX IF NOT EXISTS ix_sales_sale_date ON sales (sale_date);

CREATE TABLE IF NOT EXISTS batches (
	id SERIAL NOT NULL, 
	medicine_id INTEGER NOT NULL, 
	warehouse_id INTEGER NOT NULL, 
	batch_number VARCHAR(30) NOT NULL, 
	manufacture_date DATE NOT NULL, 
	received_date DATE NOT NULL, 
	expiry_date DATE NOT NULL, 
	unit_cost NUMERIC(12, 2) NOT NULL, 
	received_quantity INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (id, warehouse_id), 
	CHECK (received_quantity > 0), 
	CHECK (unit_cost > 0), 
	CHECK (manufacture_date <= received_date AND received_date <= expiry_date), 
	FOREIGN KEY(medicine_id) REFERENCES medicines (id), 
	FOREIGN KEY(warehouse_id) REFERENCES warehouses (id), 
	UNIQUE (batch_number)
);

CREATE INDEX IF NOT EXISTS ix_batches_expiry_date ON batches (expiry_date);

CREATE INDEX IF NOT EXISTS ix_batches_medicine_id ON batches (medicine_id);

CREATE INDEX IF NOT EXISTS ix_batches_warehouse_id ON batches (warehouse_id);

CREATE TABLE IF NOT EXISTS inventory (
	batch_id INTEGER NOT NULL, 
	quantity INTEGER NOT NULL, 
	snapshot_date DATE NOT NULL, 
	PRIMARY KEY (batch_id), 
	CHECK (quantity >= 0), 
	FOREIGN KEY(batch_id) REFERENCES batches (id)
);

CREATE TABLE IF NOT EXISTS sales_items (
	id SERIAL NOT NULL, 
	sale_id INTEGER NOT NULL, 
	warehouse_id INTEGER NOT NULL, 
	batch_id INTEGER NOT NULL, 
	quantity INTEGER NOT NULL, 
	unit_price NUMERIC(12, 2) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(sale_id, warehouse_id) REFERENCES sales (id, warehouse_id), 
	FOREIGN KEY(batch_id, warehouse_id) REFERENCES batches (id, warehouse_id), 
	UNIQUE (sale_id, batch_id), 
	CHECK (quantity > 0), 
	CHECK (unit_price > 0)
);

CREATE INDEX IF NOT EXISTS ix_items_batch_sale ON sales_items (batch_id, sale_id);
COMMIT;
