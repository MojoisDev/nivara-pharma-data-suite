# Nivara — Pharma Data & Automation Suite

**Final project summary · 13 October 2026 · Phases 1–3**

A locally runnable portfolio application for pharmaceutical Data Analyst, Python Automation Engineer, and Data Engineer roles. All three planned phases are implemented. The suite connects a relational data foundation, sales and inventory analytics, data-quality review, and scheduled reporting workflows.

**Synthetic data only.** Every business entity and value is fictional. The application contains no patient information and is not a validated clinical, regulatory, GxP, or production ERP system.

## What was delivered

### Phase 1 — Data foundation and analytics

- PostgreSQL tables for categories, medicines, distributors, warehouses, batches, inventory, sales, and sale items, with keys, relationships, constraints, and indexes.
- Deterministic data generation using seed `20251011`, covering January 2024–December 2025 across North, South, East, and West India.
- Repeatable ingestion, transaction rollback, and startup seeding that preserves an existing business database.
- SQL and Python analytics for monthly revenue, regional and category contribution, top products, stock levels, expiry exposure, stock-at-risk value, and inventory turnover.
- A customized Streamlit dashboard with Plotly charts, filters, CSV exports, and documented KPI assumptions.

### Phase 2 — Data quality and controlled review

- A validation engine with 33 versioned rules across completeness, uniqueness, validity, consistency, referential integrity, and timeliness.
- Staged source records, persisted validation runs, issue lifecycle management, quarantine evidence, review notes, and audit history.
- Explicit correction, revalidation, and approved-load controls; failed snapshots do not automatically enter the business tables.
- A Data Quality dashboard with scores, trends, a searchable findings ledger, review controls, and exports.
- Additive migration introducing seven quality tables and three nullable business metadata columns.

The clean demonstration dataset scored **100%** with no findings. The deliberately corrupted dataset produced **19 findings across 13 failing records**, scoring approximately **83.33%**. These demo results use a declared historical replay clock and do not assert that historical data is fresh today.

### Phase 3 — Workflow automation and monitoring

- Dedicated APScheduler service with configurable daily and weekly schedules; the API and dashboard do not start schedulers.
- Ordered execution: **validation → analytics refresh → Excel report → alert evaluation → email preparation/delivery**. Critical validation failures block report generation.
- PostgreSQL advisory locks, durable job requests, idempotency keys, bounded retries, subprocess timeouts, execution duration, and structured events.
- Professional XLSX workbooks with summary, sales, regional sales, inventory, near-expiry, quality findings, and explanatory notes; formatted tables, filters, frozen headers, number formats, and conditional formatting.
- Atomic report writes, unique identifiers, snapshot provenance, checksum verification, and safe downloads.
- Configurable alerts for low stock, near expiry, expired sellable stock, critical quality findings, and workflow failures; new, acknowledged, and resolved states with notification deduplication.
- Local `.eml` previews by default; environment-configured SMTP, recipient restrictions, delivery attempts, and distinct failed/uncertain states.
- Monitoring dashboard for schedules, execution history, alerts, reports, confirmed manual workflows, and email evidence.
- CLI commands and a bearer-authenticated HTTP API. Only the API health endpoint is unauthenticated; an unset token denies access to data and execution routes.
- Nine additive automation tables, persistent report storage, and health checks for PostgreSQL, application, scheduler, and API.

## Architecture and technology

Python 3.12, PostgreSQL 16, SQLAlchemy Core, Pandas, Streamlit, Plotly, APScheduler, openpyxl, Docker Compose, pytest, and Ruff. Dependencies are pinned in `requirements.lock`. No paid service is required.

```mermaid
flowchart LR
    Source[Synthetic CSVs] --> DB[(PostgreSQL)]
    DB --> Quality[Phase 2 validation]
    DB --> Analytics[Sales and inventory analytics]
    Scheduler[Dedicated scheduler] --> Workflow[Workflow controller]
    API[Authenticated local API / CLI] --> Workflow
    Workflow --> Quality
    Quality --> Analytics
    Analytics --> Workbook[XLSX report storage]
    Workbook --> Alerts[Alert evaluation]
    Alerts --> Mail[Local email preview / configured SMTP]
    DB --> Dashboard[Streamlit dashboards]
    Workflow --> DB
    Alerts --> DB
    Mail --> DB
```

## Verified business data

The final recorded Phase 3 verification preserved all eight business-table counts:

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
| **Total** | **44,365** |

Inventory snapshot: **31 December 2025**. Inventory values use acquisition cost; revenue is ex-tax. KPI definitions and filter behavior are documented in [docs/KPIS.md](docs/KPIS.md).

## Verification results

These are recorded results from the completed implementation verification, not a new test run on the summary date.

- **92 tests passed, 0 failed, 0 skipped**, including actual PostgreSQL integration tests; recorded runtime: 16.04 seconds.
- Ruff lint and formatting checks passed.
- Tests covered generation, database integrity, hand-verified KPIs, quality validation, dashboard functions, scheduler behavior, dependency order, retries, timeouts, idempotency, workbook validity, alert deduplication, email previews/mocked delivery, and database failure rollback.
- Browser checks confirmed Phase 1 sales KPIs/charts, the Phase 2 clean validation dashboard, and Phase 3 monitoring, report-library, and email-preview views.
- PostgreSQL, app, scheduler, and API were all healthy at the final recorded check.
- Service restart preserved business counts, execution history, reports, alerts, and previews; the report download still matched the host artifact.

The live verification persisted **3 executions**: two successful workflows and one deliberately invalid reporting-window failure. The subsequent daily workflow succeeded and resolved the workflow-failure alert. It also persisted **2 reports**, **85 alert conditions** (84 active, 1 resolved), and **3 email previews**. These are verification-time counts; scheduled workflows may add records later.

### Generated sample workbook

[Open the synthetic annual workbook](data/reports/synthetic_4ed6cd17-8034-5ecd-81b5-72746623b701.xlsx)

Absolute host path:

```text
/home/mujeeb_25/pharma-data-suite/data/reports/synthetic_4ed6cd17-8034-5ecd-81b5-72746623b701.xlsx
```

The workbook was reopened with openpyxl and passed ZIP integrity checks. It contains seven worksheets and seven Excel tables. Independent PostgreSQL queries confirmed the following 2025 figures:

| KPI | Verified value |
| --- | ---: |
| Net sales revenue | INR 54,539,450.97 |
| Closing stock units | 482,753 |
| Closing stock at cost | INR 70,823,412.56 |

![Automation monitoring dashboard](docs/screenshots/automation-desk.jpg)

## Start the existing workstation deployment

```bash
cd /home/mujeeb_25/pharma-data-suite
POSTGRES_PORT=55433 APP_PORT=8502 \
  docker-compose -p pharma-phase1-compose up -d --no-build
POSTGRES_PORT=55433 APP_PORT=8502 \
  docker-compose -p pharma-phase1-compose ps
```

These commands use the already-built image and existing environment. For a fresh installation or rebuild, follow [README.md](README.md) and [docs/automation.md](docs/automation.md). Keep the existing `.env`; do not replace it merely to restart services.

| Service | Local address |
| --- | --- |
| Sales and inventory dashboard | http://127.0.0.1:8502/ |
| Data Quality dashboard | http://127.0.0.1:8502/Data_Quality |
| Automation dashboard | http://127.0.0.1:8502/Automation |
| API health | http://127.0.0.1:8503/health |
| PostgreSQL | localhost:55433 |

Default schedules: **daily at 08:00** and **Monday at 09:00**, Asia/Kolkata. Historical reporting dates follow the stored inventory snapshot. Reports and previews persist in `data/reports/`; PostgreSQL uses its existing persistent volume.

### Example manual workflow

```bash
POSTGRES_PORT=55433 APP_PORT=8502 \
  docker-compose -p pharma-phase1-compose exec -T scheduler \
  pharma auto trigger --kind weekly --key summary-annual-2025 \
  --actor portfolio-reviewer --notes 'Synthetic annual briefing' \
  --start 2025-01-01 --end 2025-12-31
```

Reusing the same key with the same request returns the original execution rather than duplicating work.

### Re-run checks

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
TEST_DATABASE_URL=postgresql+psycopg://pharma:synthetic_local_only@localhost:55432/pharma_test \
  .venv/bin/pytest -q
```

The recorded test setup uses a separate local PostgreSQL test database on port **55432**. Ensure that dedicated `pharma_test` database exists before running the integration suite. Do not point tests at the portfolio database on port 55433. Local network access is required for PostgreSQL and loopback API tests. The password above is a public synthetic-demo value, not a private credential.

## Repository and documentation

| Location | Purpose |
| --- | --- |
| `src/pharma_suite/` | Data generation, database access, analytics, quality engine, and CLI |
| `src/pharma_suite/automation/` | Scheduler, controller, reports, alerts, email, storage, API, and automation CLI |
| `dashboard/` | Phase 1 dashboard and Phase 2/3 pages |
| `tests/` | Regression, unit, dashboard, and integration tests |
| `sql/` | Business initialization, KPI queries, and additive migrations |
| `config/automation.json` | Non-secret schedules, thresholds, and workflow settings |
| `data/` | Synthetic source files and runtime report/preview storage |
| `scripts/` | Local/container startup helpers |
| `compose.yaml`, `Dockerfile` | Local services and application image |
| `.env.example` | Configuration template without private secrets |
| `docs/` | Architecture, KPI definitions, design, quality, automation, screenshots, and evidence |

Key references: [README](README.md), [architecture](docs/ARCHITECTURE.md), [data quality](docs/data_quality.md), [automation](docs/automation.md), [Phase 1 verification](docs/VERIFICATION.md), [Phase 2 evidence](docs/verification_phase2.json), and [Phase 3 evidence](docs/verification_phase3.json).

## Remaining limitations

- Real SMTP delivery was intentionally not exercised; no real emails were sent during verification. Microsoft Excel GUI compatibility was not checked; workbook structure and values were checked with openpyxl.
- This is a trusted-local, single-worker deployment. Offline schedule occurrences are not backfilled automatically; interrupted executions require review and an explicit new request when appropriate.
- Historical data remains historical. Phase 1 has no source ingestion timestamp; validation reports unknown import freshness rather than inventing it.
- Local reviewer labels are attribution, not authenticated electronic signatures. Do not expose Streamlit publicly without additional access controls.
- No unresolved local deployment blocker was recorded. Clinical validation, regulatory certification, production hardening, and additional project phases are outside the completed scope.
