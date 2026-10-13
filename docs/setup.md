# Nivara — Full setup and operations guide

**Phases 1–3 — sales, inventory, data quality and workflow automation.** A locally runnable portfolio application
for pharmaceutical Data Analyst and Automation Engineer roles. PostgreSQL + SQLAlchemy Core + Pandas +
Streamlit + Plotly, with deterministic synthetic data, executable KPI SQL and tested reconciliation.

**Every entity and value is fictional. No patient information, real customer data or clinical decisions.
This application is a portfolio simulation, not a validated clinical, regulatory or production ERP system.**

## Start with Docker

Requires Docker Engine and Compose. On systems with legacy Compose, substitute `docker-compose` for
`docker compose`. The application is bound to localhost and requires no paid account.

```bash
cd /home/mujeeb_25/pharma-data-suite
test -f .env || cp .env.example .env
# Edit the demo environment if desired; never commit .env.
docker compose up --build -d
docker compose ps
docker compose logs --tail=80 app
```

Open **http://localhost:8501**. PostgreSQL is available at `localhost:55432`. The app initializes
schema and atomically loads the synthetic dataset before serving. All four services have health checks.
The database uses a named persistent volume. Startup applies additive migrations and seeds only an entirely empty business database; existing business rows and quality history are preserved.
Keep this environment separate from real business databases. Example credentials are public demo values,
not production secrets; use URL-safe credentials in the Compose URL or supply a percent-encoded URL.

```bash
docker compose stop          # Stop without deleting the database volume.
docker compose start        # Resume the services.
```

## Local Python 3.12

```bash
cd /home/mujeeb_25/pharma-data-suite
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
test -f .env || cp .env.example .env
```

Or use `uv venv --python 3.12`, `uv pip sync requirements.lock`, and `uv pip install --no-deps -e .`.
Dependencies including development tools are pinned in `requirements.lock`.

Start only PostgreSQL through Compose, or point `DATABASE_URL` in `.env` at a dedicated local PostgreSQL
database, then:

```bash
docker compose up -d postgres
pharma init
pharma generate                 # Save deterministic CSVs + synthetic manifest.
pharma seed                     # Seed only an empty database; preserve existing data.
pharma verify                   # Print actual row counts.
streamlit run dashboard/app.py --server.address=127.0.0.1
```

If PostgreSQL/Docker is unavailable, use the explicit SQLite demo path:

```bash
export DATABASE_URL=sqlite:///data/pharma_demo.db
pharma ingest
streamlit run dashboard/app.py --server.address=127.0.0.1
```

SQLite supports the same dashboard and portable tests. PostgreSQL SQL and integration tests still
require a PostgreSQL server; the demo is not evidence those tests passed.

## Data Quality — Phase 2

A dedicated **Data Quality** page provides stored validation scores, run trends, a filterable issue ledger, raw quarantine evidence, manual review, audit history and CSV exports. The 33 versioned rules cover six dimensions plus batch expiry, sales chronology and stock reconciliation. Read [the complete rule catalog, scoring contract and lifecycle](data_quality.md).

```bash
pharma dq generate
pharma dq validate --dataset demo-clean
pharma dq validate --dataset demo-corrupted
pharma dq verify-manifest
pharma dq report --dataset demo-corrupted
```

With Compose, prefix commands with `docker compose exec app`. Clean demo: 100%, no findings. Corrupted demo: 19 expected and detected findings, 13 failing records, 83.33% overall. Timeliness uses an explicit historical replay clock, not today's freshness. Source corrections and approved load require reviewer notes, current revision and revalidation; no failed snapshot enters production. Migration `sql/002_data_quality.sql` adds seven quality tables and three nullable metadata columns without resetting Phase 1.

## Automation — Phase 3

The **Automation** page adds confirmed manual workflows, daily/weekly scheduler status, execution and retry history, alert review, XLSX downloads and email previews. A dedicated scheduler validates a consistent database snapshot, refreshes analytics, generates an atomic workbook, evaluates alert conditions and prepares a safe local email preview. PostgreSQL locks prevent duplicate schedulers and overlapping executions. [Architecture, configuration, API, safety controls and recovery](automation.md).

```bash
# With Compose running; this workstation uses project pharma-phase1-compose.
docker compose exec scheduler pharma auto trigger --kind weekly --key annual-2025 \
  --actor portfolio-reviewer --notes 'Synthetic annual briefing' --start 2025-01-01 --end 2025-12-31
docker compose exec scheduler pharma auto list --entity executions
docker compose exec scheduler pharma auto scheduler-status
```

Generated workbooks and .eml previews persist in `data/reports/`. Defaults: daily 08:00, Monday 09:00, Asia/Kolkata. `MAIL_MODE=preview` opens no SMTP connection. External delivery requires explicit mode, allowlisting and TLS configuration. The HTTP API is loopback-bound and requires a bearer token for every data/write endpoint; unset token denies access. Keep `.env` ignored and generate the local token as described in [setup](automation.md#linux-and-docker-deployment).

Migration `sql/003_automation.sql` adds nine tables and preserves existing business/quality data. Verification includes a full-data workbook with INR 54,539,450.97 annual revenue and INR 70,823,412.56 closing stock value, independently checked against PostgreSQL. [Executed evidence](verification_phase3.json) includes a successful workflow, deliberate invalid-window failure and recovery, safe download and request deduplication. All mail stayed in preview mode.

## Dataset

Fixed seed **20251011**, 24 months **January 2024–December 2025**, snapshot **31 December 2025**.
Four Indian regions: North/Delhi, South/Chennai, East/Kolkata, West/Mumbai. 120 fictional medicines across
8 categories; four batch receipt waves per medicine/warehouse; FEFO sale allocation, discounted prices,
and nonnegative stock. Amounts are INR; inventory is valued at acquisition cost.

| Table | Deterministic rows |
| --- | ---: |
| categories | 8 |
| medicines | 120 |
| distributors | 24 |
| warehouses | 4 |
| batches | 1,920 |
| inventory | 1,920 |
| sales | 8,820 |
| sales_items | 31,549 |

CSV artifacts in `data/synthetic/` are inspectable copies of generated data. Ingestion uses the generator
rather than trusting manually edited CSVs. `manifest.json` records seed, date, synthetic status and counts.
Ingestion replaces the suite's eight tables within one transaction; failure preserves previous records.

## Dashboard

Custom Nivara operations-desk design: paper background, forest teal, serif headlines, quiet provenance
labels and an amber expiry review queue. Revenue/units/closing-cost/turnover KPIs, monthly trend,
regional contribution, therapy mix, top products, batch risk ledger and stock by hub. Date, region,
category and expiry-horizon filters apply consistently. Each analytical section offers filtered CSV export.

Inventory is reconstructed at the selected end date, including opening movements. Changing the sales
start date does not erase opening stock. Turnover uses exact daily average inventory, not a revenue/stock
shortcut. Monetary aggregation uses integer paise. See [KPI definitions](KPIS.md) for formulas,
expiry boundaries, valuation, filter scope and hand-calculated examples.

Mobbin research was attempted through the installed connector, which required a paid plan. No paid
services were used and no inaccessible screens are claimed as design references. See [design notes](DESIGN.md).

## Repository and architecture

```text
src/pharma_suite/  foundation, quality/ and automation/ workflows, migrations and CLI
sql/              PostgreSQL schema initializer and eight KPI queries
scripts/          container startup
data/             synthetic CSVs, quality demos and independent fault manifest
dashboard/        sales, data quality and automation desks with custom CSS
tests/fixtures/  hand-verified fixture
tests/           portable, PostgreSQL and dashboard tests
config/           quality thresholds and automation schedules/limits
docs/             architecture, KPI/quality contracts, design and verification
```

See [architecture and schema](ARCHITECTURE.md) for the ER diagram, constraints, indexes, data flow,
transaction boundaries and limitations. `sql/001_foundation.sql` is an idempotent v1 initializer,
mirroring SQLAlchemy metadata; it does not migrate an incompatible existing schema.

For raw initialization with psql:

```bash
psql 'postgresql://pharma:synthetic_local_only@localhost:55432/pharma' \
  -v ON_ERROR_STOP=1 -f sql/001_foundation.sql
```

SQL files under `sql/queries/` accept SQLAlchemy named parameters (`:start_date`, `:end_date`,
`:region`, `:category`, and for risk queries `:risk_cutoff`). NULL region/category means all.
Example execution from the project root:

```python
from datetime import date
from pathlib import Path
from sqlalchemy import text
from pharma_suite.db import create_db

params = dict(
    start_date=date(2025, 1, 1),
    end_date=date(2025, 12, 31),
    region=None,
    category=None,
    risk_cutoff=date(2026, 3, 31),
)
with create_db().connect() as conn:
    result = conn.execute(text(Path("sql/queries/monthly_revenue.sql").read_text()), params)
    print(result.mappings().all())
```

Validate date bounds in raw SQL clients: end must not exceed the snapshot, start ≤ end and
risk cutoff ≥ end. Dashboard and Python report functions enforce their own date contract.

## Tests and formatting

```bash
source .venv/bin/activate
pytest -q
ruff check .
ruff format --check .
```

Portable tests use temporary SQLite databases, a small hand-verified fixture and Streamlit AppTest.
PostgreSQL tests are explicitly skipped unless `TEST_DATABASE_URL` is set. They refresh tables and must
run against a **separate disposable database**, never a real data warehouse.

```bash
docker compose exec postgres createdb -U pharma pharma_test
export TEST_DATABASE_URL=postgresql+psycopg://pharma:synthetic_local_only@localhost:55432/pharma_test
pytest -q
```

Tests cover determinism, 24-month coverage, nonnegative reconciliation, invalid imports, keys/checks,
idempotent ingestion, rollback, independent revenue/risk/turnover expectations, as-of dates and
Streamlit filters. PostgreSQL tests also execute all eight SQL KPI files against the hand fixture.
Phase 1 evidence is in [verification](VERIFICATION.md); Phase 2 evidence is in [verification_phase2.json](verification_phase2.json), and Phase 3 results are in [verification_phase3.json](verification_phase3.json). Quality tests also cover all six dimensions, issue transitions, quarantine, controlled load and database-trigger rollback.

## Portfolio screenshots

Actual screenshots: [automation desk](screenshots/automation-desk.jpg), [data quality desk](screenshots/quality-desk.jpg), [sales desk](screenshots/sales-desk.jpg),
[revenue charts](screenshots/revenue-charts.jpg), and
[inventory watch](screenshots/inventory-watch.jpg).

Follow [the screenshot checklist](DESIGN.md#screenshot-checklist). Keep the synthetic label, report
window and units visible. Record sales, product ranking and expiry review screens from the running app.
Do not present generated images or unrun tests as proof of the application.

## Troubleshooting

- **Docker socket permission denied:** use `sudo docker compose ...` if your workstation policy permits,
  or ask its administrator to configure Docker access. This project does not change group permissions.
- **`docker compose` unknown:** try installed `docker-compose`; otherwise install the official Compose
  plugin through your Linux package manager (`sudo apt-get install docker-compose-plugin` where available).
- **Port already in use:** stop the process that owns it or change `POSTGRES_PORT` / `APP_PORT` in `.env`.
  For local Python, match `DATABASE_URL` to the new database port.
- **Empty dashboard:** run `pharma seed`, then press Refresh database snapshot. Read CLI errors if import fails.
- **Connection refused:** check `docker compose ps`, database health, host port and DATABASE_URL. Inside a
  container the database hostname is `postgres`, not `localhost`.
- **Authentication fails after editing `.env`:** PostgreSQL's existing volume retains its original role
  password. Restore the matching environment or explicitly update the role through an authorized admin.
- **Legacy Compose `ContainerConfig` error on rebuild:** version 1 can fail when recreating containers
  against a newer Docker Engine. Prefer the current Compose plugin. For this stateless application,
  the following replaces only the app container and preserves PostgreSQL and its volume:

  ```bash
  docker-compose stop app
  docker-compose rm -f app
  docker-compose up -d --no-deps app
  ```

- **Schema upgrade:** run `pharma init` or apply `sql/002_data_quality.sql` after v1. The additive migration preserves rows. Incompatible unrelated schema drift requires review; no reset is automated.
- **Changes not visible:** cache lasts 60 seconds; use the dashboard refresh button.
- **Database unavailable:** use the explicit SQLite fallback above and run portable tests; return to
  PostgreSQL and run integration tests after recovery.

Phases 1–3 are implemented locally. Paid services, public hosting, real patient data and external email delivery are excluded from the verified demo.

## Verified running instance

This workstation uses PostgreSQL at `localhost:55433` and the app at [localhost:8502](http://127.0.0.1:8502), because the original Phase 1 instance occupies the default ports. The quality desk is at [Data Quality](http://127.0.0.1:8502/Data_Quality). To start this same instance with the installed legacy Compose executable:

```bash
POSTGRES_PORT=55433 APP_PORT=8502 docker-compose -p pharma-phase1-compose up --build -d
POSTGRES_PORT=55433 APP_PORT=8502 docker-compose -p pharma-phase1-compose exec app pharma dq report --dataset demo-corrupted
```

If legacy Compose reports `ContainerConfig`, use the app-only replacement procedure above with the same port variables and `-p pharma-phase1-compose`. Never remove the database volume to upgrade. The Phase 3 verification artifact records final tests and live API/scheduler/workbook checks, including actual PostgreSQL. API health is available at http://127.0.0.1:8503/health; every data or write route requires a bearer token.
