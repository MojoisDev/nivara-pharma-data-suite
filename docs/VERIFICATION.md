# Implementation verification — 11 October 2026

This report records checks actually executed for Phase 1; no speed or load benchmark is claimed.

## Results

- Python 3.12.3; runtime and development dependencies synchronized to `requirements.lock`.
- Final full pytest run with a dedicated PostgreSQL test database: **18 passed, 0 failed, 0 skipped**.
- Portable run without PostgreSQL URL: **15 passed, 3 explicitly skipped**.
- `ruff check .`: passed; `ruff format --check .`: passed.
- PostgreSQL 16 container: initialized and deterministic dataset loaded. Repeated ingestion preserved
  counts; rollback after a constraint failure and invalid-import rejection were tested.
- Version 1 SQL initializer executed twice against an independent empty PostgreSQL database; both succeeded.
- All eight KPI SQL files executed against the independent hand fixture. Filtered SQL revenue, stock,
  risk and turnover also matched Python reporting against the full dataset.
- SKU grouping tested with two products sharing a display name; they remain separate products and
  the invoice count stays distinct. Batch inventory remains one record when sold on multiple invoices.
- Streamlit AppTest: startup, zero-region selection, zero KPIs/undefined turnover, and region re-selection passed.
- Real browser: PostgreSQL dashboard rendered; sales and inventory tabs inspected; 90-day horizon verified.
- CSV downloaded through the actual monthly export button: 12 records and ₹54,539,450.97 total revenue
  for calendar 2025/all regions/categories. File saved in the workstation Downloads folder.
- Docker image built successfully, running as non-root. Full Compose deployment started; PostgreSQL and
  app health checks passed. Native and Compose HTTP health endpoints returned 200.

## Actual PostgreSQL counts

| Table | Rows |
| --- | ---: |
| categories | 8 |
| medicines | 120 |
| distributors | 24 |
| warehouses | 4 |
| batches | 1,920 |
| inventory | 1,920 |
| sales | 8,820 |
| sales_items | 31,549 |

Counts were read from both the native-workflow PostgreSQL database and Compose PostgreSQL, not merely
copied from generator expectations. All data covers 2024–2025 and is synthetic.

## Running services and recovery commands

The final Compose deployment is **http://localhost:8502**, database **localhost:55433**.
Temporary verification ports avoid conflicts with the native dashboard at **http://localhost:8501**
and its separate test/workflow PostgreSQL container `pharma-phase1-db` at port 55432.
Default fresh setup ports in `.env.example` remain 8501 and 55432.

Current Compose stack operations from the project root:

```bash
POSTGRES_PORT=55433 APP_PORT=8502 docker-compose -p pharma-phase1-compose ps
POSTGRES_PORT=55433 APP_PORT=8502 docker-compose -p pharma-phase1-compose logs --tail=60 app
POSTGRES_PORT=55433 APP_PORT=8502 docker-compose -p pharma-phase1-compose stop
POSTGRES_PORT=55433 APP_PORT=8502 docker-compose -p pharma-phase1-compose start
```

The workstation's Docker socket needs elevated access; prepend `sudo` if appropriate for its policy.
No user groups or system permissions were modified. The standalone verification database can be stopped
with `docker stop pharma-phase1-db`; its container preserves its synthetic data while stopped.

The workstation has Docker Engine 29.1.3 and legacy Compose 1.29.2, but no `docker compose` plugin.
Fresh creation worked; legacy Compose recreation after a rebuild failed with `KeyError: ContainerConfig`.
The image built successfully. Recovery replaced only the app container, leaving PostgreSQL's volume intact:

```bash
POSTGRES_PORT=55433 APP_PORT=8502 docker-compose -p pharma-phase1-compose stop app
POSTGRES_PORT=55433 APP_PORT=8502 docker-compose -p pharma-phase1-compose rm -f app
POSTGRES_PORT=55433 APP_PORT=8502 docker-compose -p pharma-phase1-compose up -d --no-build app
```

This recovery was executed and the final container's health and database counts were checked.
A current Compose plugin is recommended for repeated rebuilds; installing system packages was out of scope.

## Screenshots

Real browser captures, not generated design images:

- `docs/screenshots/sales-desk.jpg`: header, scope and sales KPIs.
- `docs/screenshots/revenue-charts.jpg`: revenue/region charts, therapy mix and product table.
- `docs/screenshots/inventory-watch.jpg`: inventory KPIs, review notice and batch ledger.

## Limitations and research blocker

The installed Mobbin connector was invoked but returned a paid-plan requirement. No screens were available;
no paid service was used. The dashboard design is original and the research limitation remains disclosed.

No production deployment, clinical validation, load benchmark, cross-browser matrix or formal accessibility
audit was performed. Real transactions, patient records and Phase 2/3 are outside this phase. Ingestion
atomically replaces its eight dedicated synthetic tables: never aim it at real business data.

## Implemented file inventory

- `.dockerignore`
- `.env.example`
- `.gitignore`
- `.streamlit/config.toml`
- `Dockerfile`
- `README.md`
- `compose.yaml`
- `dashboard/app.py`
- `dashboard/style.css`
- `data/synthetic/batches.csv`
- `data/synthetic/categories.csv`
- `data/synthetic/distributors.csv`
- `data/synthetic/inventory.csv`
- `data/synthetic/manifest.json`
- `data/synthetic/medicines.csv`
- `data/synthetic/sales.csv`
- `data/synthetic/sales_items.csv`
- `data/synthetic/warehouses.csv`
- `docs/ARCHITECTURE.md`
- `docs/DESIGN.md`
- `docs/KPIS.md`
- `docs/screenshots/inventory-watch.jpg`
- `docs/screenshots/revenue-charts.jpg`
- `docs/screenshots/sales-desk.jpg`
- `pyproject.toml`
- `requirements.lock`
- `scripts/start.sh`
- `sql/001_foundation.sql`
- `sql/queries/inventory_turnover.sql`
- `sql/queries/monthly_revenue.sql`
- `sql/queries/near_expiry.sql`
- `sql/queries/revenue_by_category.sql`
- `sql/queries/revenue_by_region.sql`
- `sql/queries/stock_at_risk.sql`
- `sql/queries/stock_levels.sql`
- `sql/queries/top_products.sql`
- `src/pharma_suite/__init__.py`
- `src/pharma_suite/analytics.py`
- `src/pharma_suite/cli.py`
- `src/pharma_suite/db.py`
- `src/pharma_suite/generate.py`
- `src/pharma_suite/schema.py`
- `tests/conftest.py`
- `tests/fixtures/hand_verified.json`
- `tests/test_dashboard.py`
- `tests/test_foundation.py`
- `tests/test_postgres.py`
- `docs/VERIFICATION.md` (this report)
