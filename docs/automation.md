# Workflow automation — Phase 3

Nivara now adds local reporting workflows, XLSX briefings, operational alert review and a preview-first mail outbox. Every business value is synthetic. This portfolio is not validated clinical, regulatory, GxP or FDA-compliant software.

## Architecture

```mermaid
flowchart LR
  C[Local CLI / confirmed Streamlit action] --> Q[(Durable workflow queue)]
  API[Loopback HTTP API + bearer token] --> Q
  S[Dedicated APScheduler process] --> Q
  Q --> W[Single controller + bounded Linux subprocess]
  DB[(PostgreSQL business snapshot)] --> V[Phase 2 validation + persisted run]
  W --> V
  V --> G{Critical findings?}
  G -->|yes| F[Failed execution + alerts + preview]
  G -->|no| A[Phase 1 analytics on same captured snapshot]
  A --> R[Atomic XLSX + report registry]
  R --> L[Alert lifecycle evaluation]
  L --> E[Mail outbox + local EML preview]
  E -->|explicit SMTP configuration| SMTP[Allowlisted recipients + TLS + bounded retries]
  Q --> M[Streamlit Automation desk]
  R --> M
  L --> M
  E --> M
```

The implementation reuses SQLAlchemy Core, the Phase 2 rule engine and the Phase 1 KPI functions. It adds APScheduler 3.x and openpyxl rather than a task broker, Redis or another web framework. The small HTTP interface uses Python's standard-library server and is deliberately restricted to trusted local use. See the [APScheduler user guide](https://apscheduler.readthedocs.io/en/3.x/userguide.html) for coalescing, misfires and instance limits, and [openpyxl tables](https://openpyxl.readthedocs.io/en/stable/worksheet_tables.html) for workbook table behavior.

## Schema and integration

Migration `sql/003_automation.sql` is additive and repeatable after migrations 001 and 002. `pharma init` applies it automatically. No workflow refreshes, deletes, approves or repairs the eight business tables. The app still seeds only a completely empty business database.

| Table | Persisted evidence |
| --- | --- |
| auto_executions | Unique request/key/hash, cadence, actor/notes, frozen non-secret configuration, dates, status, attempts, timestamps, duration and result |
| auto_attempts | Attempt number, terminal state, timestamps, duration and error type |
| auto_events | Ordered stage logs and structured details; execution FK |
| auto_reports | Unique execution/report ID, filename, checksum, size, snapshot hash and KPI/quality summary |
| auto_alerts | Stable condition identity, record IDs, reason, severity, lifecycle, revision and notification revision |
| auto_alert_events | New/changed/reopened/acknowledged/resolved history and reviewer evidence |
| auto_emails | One prepared message per execution, preview filename/checksum, recipients, state and delivery attempts |
| auto_mail_events | Preparation and delivery outcomes without SMTP credentials |
| auto_scheduler_state | Singleton owner, heartbeat, effective configuration and next job times |

Foreign keys link observations to executions/alerts/emails. Unique request keys, report-per-execution and message-per-execution constraints prevent repeat creation. Indexes cover execution status, alert status/type and audit joins. Database version 3 is recorded in `dq_schema_migrations`.

`analytics.facts_from_connection` allows the automation module to capture normalized sales facts, batch facts and source rows inside the same repeatable-read PostgreSQL transaction. Snapshot hashing and quality validation refer to those exact rows. Analytics uses the captured facts even if business data changes afterwards. No live report computes stock from a joined line-level inventory sum.

## Workflow and scheduling behavior

Default schedules are **daily at 08:00** and **Monday at 09:00**, timezone **Asia/Kolkata**. Daily reports cover the snapshot's final day; weekly reports cover its last seven days. Explicit start/end parameters generate any supported inclusive window. Reporting dates never exceed the inventory snapshot. A historical snapshot remains historical even when a schedule runs today.

Order: capture → stage/validate → critical-quality gate → analytics refresh → XLSX → alert evaluation → email preparation/delivery. Critical findings block report generation by default. Noncritical findings remain visible in the workbook and indicate a review artifact, not approved source data. The global setting can be changed deliberately, but never changes Phase 2's production approval gate.

Streamlit and the API only enqueue requests. A dedicated scheduler/controller processes the queue serially. PostgreSQL session advisory locks prevent duplicate schedulers and overlapping controller executions across CLI/processes. SQLite uses Linux file locks and requires one shared report directory; PostgreSQL is the supported deployed target.

Every manual request requires an idempotency key. Repeating the same key/request returns the existing execution; reusing the key with changed dates, cadence or configuration is rejected. Scheduled keys include cadence, the local firing minute and effective configuration hash. APScheduler uses one instance per schedule, coalescing and a 300-second misfire grace period. Its cron triggers are reconstructed from configuration on restart; persisted queued requests survive. **Schedules missed while the scheduler process was offline are not automatically backfilled.** Trigger an explicit historical report if needed.

Each attempt runs in a separate process with a hard deadline, followed by SIGTERM and then SIGKILL if required. Linux parent-death protection terminates workers when their controller is killed. Transient database/OS errors retry up to the configured attempt limit, with delay; invalid data/configuration is not blindly retried. Interrupted `running` records become failed on restart and remain auditable. They are not automatically replayed; submit a new reviewed key after examining partial-stage history. Completed validation runs and registered files remain evidence even if a later stage fails. Partial/unregistered files are not exposed through the report registry.

If the database itself is unavailable, a controller cannot persist new database evidence. Health turns unhealthy and Compose restarts the process. After database recovery, inspect interrupted records and the container logs; no successful run is invented to cover an outage.

## Configuration

`config/automation.json` contains validated non-secret settings. Configured parameters are frozen into each queued execution. An edited configuration affects future requests; restart the scheduler to change cron triggers. The effective scheduler configuration is visible in status and monitoring.

| Setting | Default | Meaning |
| --- | --- | --- |
| timezone | Asia/Kolkata | IANA scheduling timezone |
| daily_cron | `0 8 * * *` | Five-field daily cron |
| weekly_cron | `0 9 * * mon` | Five-field weekly cron |
| low_stock_units | 100 | Alert if aggregate medicine/warehouse closing quantity is strictly below this value |
| near_expiry_days | 90 | Inclusive snapshot-to-expiry alert horizon |
| max_attempts | 3 | Workflow attempt limit |
| timeout_seconds | 120 | Hard deadline per attempt |
| retry_delay_seconds | 2 | Delay between transient retries |
| stop_on_critical | true | Block publication for critical validation findings |
| assessment_at | null | Actual UTC assessment clock; explicit historical clock permitted for replay |
| attach_report | true | Attach generated workbook to the prepared message |

Environment overrides: `AUTOMATION_CONFIG`, `REPORT_DIR`, `DAILY_CRON`, `WEEKLY_CRON`, `SCHEDULER_TIMEZONE`, `DQ_ASSESSMENT_AT`. Empty optional overrides are ignored. Compose mounts the config file read-only and shares the report directory among app, scheduler and API. SMTP credentials and API token are read from the environment and never stored in configuration JSON or execution logs.

Phase 1 has no ingestion timestamp. Workflow validation sets `source_received_at` to missing and reports that timeliness finding instead of calling extraction an import. Its feed date is the latest stored business transaction date. With today's clock, the 2025 feed is also delayed. An explicit historical clock does not make the unknown import timestamp known. This differs intentionally from Phase 2's self-contained demo envelopes, which declare their synthetic import clocks.

## Excel reports and samples

Each UUID-addressed XLSX contains seven worksheets:

1. Executive Summary: revenue, units, invoices, closing stock/value, risk value, turnover and quality summary.
2. Sales Analytics: monthly revenue and units from the selected period.
3. Regional Sales: fulfilling-region revenue and units.
4. Inventory Levels: one row per batch with reconstructed closing stock, cost value and expiry status.
5. Near Expiry: positive held stock inside the inclusive horizon; expired held stock remains in Inventory Levels.
6. Data Quality: actual persisted rule findings and suggested remediation.
7. Notes: synthetic disclaimer, workflow/quality IDs, snapshot hash, clocks and calculation assumptions.

The workbook includes branded headers, native Excel tables/filters, frozen headers, numeric formats and stock/expiry conditional formatting. Text that could become an Excel formula is escaped. KPI values are computed in Python from actual SQL facts and written as values, so viewing does not depend on Excel recalculation. No sample KPI is hardcoded.

Artifacts use a temporary file, fsync and atomic rename, then a registered SHA-256 checksum. Downloads resolve only registered UUIDs inside the report directory and reject traversal, missing files and changed contents. Repeating a request creates no new report; retrying a registered report with a different snapshot is rejected. Runtime XLSX/EML artifacts are ignored by Git and excluded from Docker build context.

Actual sample IDs, absolute host paths, persisted counts and verification results are in `docs/verification_phase3.json`. The workbook was reopened using openpyxl and checked against independent SQL revenue and inventory sums. No Microsoft Excel GUI compatibility test is claimed.

## Alert rules and lifecycle

- **Low stock**: medicine/warehouse aggregate held units below configured threshold; exhausted batches alone do not create false product shortages.
- **Near expiry**: positive stock whose expiry falls from its inventory snapshot date through the configured horizon.
- **Expired sellable**: positive expired stock explicitly flagged sellable. Legitimate expired unavailable inventory is not this alert.
- **Critical quality**: critical findings in the latest run for each staged source; historical production snapshot sources are excluded when superseded by a newer production snapshot validation.
- **Workflow failure**: the most recent terminal execution for a cadence failed or timed out. A later successful cadence execution resolves its failure condition.

Severity, reason, record IDs, first/last detection and condition revisions are persisted. A stable unchanged condition retains its ID and acknowledgement and generates no new notification detail. Changed or recurring conditions become `new`; disappearance becomes `resolved`. Acknowledgement requires a reviewer and notes and never hides the underlying condition. Alert state and its audit event commit atomically.

Expiry alerts refer to **stored stock snapshot dates**, not present physical stock. Current-time age is represented by the data-quality timeliness checks. A reporting workflow prepares only pending new/revised/resolved alert details; unchanged conditions may still count in the monitoring desk but are not repeatedly listed as fresh alerts in email. Resolution discovered after final workflow status becomes pending for the next prepared summary. This is an explicit local outbox, not a real-time pager.

## Email safety and delivery

Default `MAIL_MODE=preview` writes an inspectable `.eml` containing text/HTML summary and optional XLSX attachment. No SMTP connection opens, even if SMTP credentials are present. Tests prohibit real SMTP connections and explicitly mock delivery.

SMTP requires `MAIL_MODE=smtp`, valid sender/recipients and an exact `SMTP_ALLOWED_RECIPIENTS` allowlist. Nonlocal servers or real external addresses additionally require `SMTP_ALLOW_EXTERNAL=true`. External SMTP requires `SMTP_TLS=starttls` or `ssl`; unencrypted SMTP is restricted to a deliberately configured local test server. Never turn on external delivery merely to verify this portfolio.

Environment fields: `SMTP_HOST`, `SMTP_PORT`, `SMTP_TLS`, `SMTP_FROM`, `SMTP_RECIPIENTS`, `SMTP_ALLOWED_RECIPIENTS`, `SMTP_ALLOW_EXTERNAL`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_MAX_ATTEMPTS` (1–5). Keep secrets in ignored `.env`, a local secret store or the process environment.

Delivery states: `preview`, `queued`, `sending`, `sent`, `failed`, `uncertain`. Definite transient SMTP rejection and pre-send connection failures retry within the configured bound. Permanent rejection fails. Disconnect during submission, partial recipient acceptance or an interrupted in-flight send is uncertain and is never automatically re-sent. SMTP has no end-to-end exactly-once guarantee; reconcile such cases with the mail server. Failed/uncertain delivery prevents a successful workflow result. Preview is an explicitly successful local preparation step, not proof of delivery.

## CLI and trusted-local API

```bash
pharma init
pharma auto run --kind weekly --key portfolio-annual-2025 --actor portfolio-reviewer \
  --notes 'Reviewed synthetic annual briefing' --start 2025-01-01 --end 2025-12-31
pharma auto trigger --kind daily --key manual-daily-001 --actor portfolio-reviewer --notes 'Queue synthetic daily briefing'
pharma auto list --entity executions
pharma auto list --entity reports
pharma auto list --entity alerts
pharma auto evaluate-alerts
pharma auto acknowledge --id ACTUAL_ALERT_ID --actor portfolio-reviewer --notes 'Reviewed batch evidence'
pharma auto report --id ACTUAL_REPORT_UUID --output /tmp/synthetic-briefing.xlsx
pharma auto email-preview --id ACTUAL_EMAIL_UUID
pharma auto scheduler-status
pharma auto schedule
```

`run` executes immediately through the same bounded controller; `trigger` queues for the running scheduler. A repeated completed key returns the original terminal record. CLI errors exit nonzero. `python -m pharma_suite.automation.cli ...` is equivalent. `deliver-email --id ...` explicitly processes a queued message under the safety policy; preview messages remain previews.

The API binds to loopback by default: `pharma auto serve --host 127.0.0.1 --port 8503`. Compose binds its container port only to host `127.0.0.1`. Every data and write endpoint requires `Authorization: Bearer <AUTOMATION_API_TOKEN>`; an unset token denies access. Only `/health` is unauthenticated and returns connectivity status. Write bodies are validated, size-limited JSON and queueing requires `Idempotency-Key`.

| Method/path | Behavior |
| --- | --- |
| POST /workflows | Queue cadence/actor/notes and optional ISO start/end |
| GET /executions | Latest 100 requests and execution states |
| GET /executions/UUID | One execution record |
| GET /scheduler | Owner/heartbeat/health/next times |
| GET /reports | Latest registered artifact metadata |
| GET /reports/UUID/download | Checksum-verified XLSX bytes |
| GET /alerts | Latest alert records |
| POST /alerts/ID/acknowledge | Reviewer/evidence attribution |
| GET /emails | Prepared message and delivery history |
| GET /emails/UUID/preview | Checksum-verified RFC822 preview |
| POST /emails/UUID/deliver | Explicit policy-controlled delivery attempt |

Use a local client that reads its token from the environment; do not paste secrets into URLs or source files. The API is not an Internet-facing server. Streamlit assumes a trusted local workstation, and reviewer labels are not authenticated electronic signatures. Do not publish the UI with execution forms through a public tunnel.

## Linux and Docker deployment

```bash
cp .env.example .env                       # On a NEW setup only; preserve an existing .env.
python3 - <<'PY'
from pathlib import Path
import secrets
with Path('.env').open('a') as stream:
    stream.write('\nAUTOMATION_API_TOKEN=' + secrets.token_urlsafe(32) + '\n')
Path('.env').chmod(0o600)
PY
mkdir -p data/reports
docker compose up --build -d
docker compose ps
docker compose exec scheduler pharma auto scheduler-status
docker compose exec scheduler pharma auto run --kind weekly --key sample-2025 --actor portfolio-reviewer \
  --notes 'Synthetic annual sample' --start 2025-01-01 --end 2025-12-31
```

Report storage is a persistent bind directory `data/reports`; PostgreSQL retains its existing named volume. The image runs as UID 1000. If your Linux account uses another UID, grant that container UID write access to this dedicated report directory using your workstation policy, or configure the container user; do not make the directory world-writable. All four services have health checks.

This workstation uses **app 8502**, **PostgreSQL 55433**, **API 8503**, project `pharma-phase1-compose`. Prefix Compose commands with `POSTGRES_PORT=55433 APP_PORT=8502` and use `docker-compose -p pharma-phase1-compose` here. Defaults on a fresh workstation remain 8501/55432/8503.

With legacy Compose v1 and newer Docker, recreation may fail with `ContainerConfig`. Build first, then replace only the stateless containers:

```bash
POSTGRES_PORT=55433 APP_PORT=8502 docker-compose -p pharma-phase1-compose build app
POSTGRES_PORT=55433 APP_PORT=8502 docker-compose -p pharma-phase1-compose stop scheduler api app
POSTGRES_PORT=55433 APP_PORT=8502 docker-compose -p pharma-phase1-compose rm -f scheduler api app
POSTGRES_PORT=55433 APP_PORT=8502 docker-compose -p pharma-phase1-compose up -d --no-build
```

Never remove the database volume to upgrade. For native Linux, use three terminals with the same DATABASE_URL/REPORT_DIR: `streamlit run dashboard/app.py --server.address=127.0.0.1`, `pharma auto schedule`, and optionally `pharma auto serve`. There is no scheduler thread inside Streamlit or the API.

## Monitoring desk

The Automation page shows all-time success/failure/queue counts, scheduler health and next execution times, last-100 execution/attempt/stage history, a confirmed manual queue form, alert filters and acknowledged review, lifecycle audit, checksum-verified workbook downloads, KPI provenance and email preview/status. Repeated form submission uses the same key until explicitly preparing a new request. Refresh reads persisted evidence; it does not start jobs or schedulers.

## Tests and troubleshooting

```bash
source .venv/bin/activate
pytest -q
TEST_DATABASE_URL=postgresql+psycopg://pharma:synthetic_local_only@localhost:55432/pharma_test pytest -q
ruff check .
ruff format --check .
```

Use a disposable test database. Tests cover all existing phases, hand-calculated revenue/stock, XLSX structure/tables, preview attachments, rule ordering, queue/registry idempotency, actual bounded subprocess execution, scheduler callbacks/exclusion, forced database-trigger failures, hard timeout, retry limits, changed snapshot protection, formula injection, alert state/audit atomicity, authenticated API boundaries and confirmed Streamlit queueing. Mocked SMTP covers transient rejection and ambiguous disconnect without any real email delivery.

- **Scheduler unhealthy/not started**: inspect `docker compose logs scheduler`, database health and status. A second scheduler exits because another owner holds the lock; do not scale this service.
- **Queued forever**: start the scheduler, check its heartbeat, and inspect running/failed jobs. The UI only queues.
- **Invalid cron/timezone**: fix the JSON/environment setting and restart the scheduler; configuration is rejected before scheduling.
- **Report write failure**: check bind-directory ownership/free disk space. Atomic writes preserve an existing file on failure.
- **Missing/checksum-failed download**: restore the report directory from backup; a database row alone cannot recreate an artifact. Generate a new reviewed request if restoration is unavailable.
- **Critical validation failure**: review Phase 2 findings and correct/revalidate explicitly. Workflows do not bypass production constraints or silently fix dates/amounts.
- **Mail failed/uncertain**: inspect outbox/delivery history and explicit SMTP policy. Uncertain messages require manual server reconciliation; do not blindly resend.
- **HTTP 401**: configure a local API token and send a bearer header. An empty token is intentionally denied.
- **Database outage**: restore PostgreSQL, let Compose restart unhealthy processes, inspect interrupted executions and manually submit a new reviewed key where appropriate.

Known limits: one local worker, no scheduler offline backfill, no multi-tenant roles or tamper-proof audits, no retention cleanup, no external mail verification, no Microsoft Excel GUI test, and portfolio-scale Pandas extracts. A large warehouse would need SQL aggregates/pagination and formal migrations/identity governance. No performance benchmark or regulatory certification is claimed.

## Implementation file inventory

Created `src/pharma_suite/automation/` modules: `config`, `schema`, `migrations`, `storage`, `reporting`, `alerts`, `mail`, `workflow`, `worker`, `scheduler`, `api`, `cli` and package initializer. Added `dashboard/pages/3_Automation.py`, `config/automation.json`, `sql/003_automation.sql`, five `tests/test_automation*.py` modules, this document, `docs/verification_phase3.json`, screenshots and runtime XLSX/EML artifacts under `data/reports`.

Updated core database/CLI integration, the reusable analytics connection reader, `tests/conftest.py` SMTP safety fixture, dependency manifest/lock, Dockerfile/Compose, environment example, Git/Docker ignores, README and architecture/KPI documentation. The existing generator and eight business tables are preserved.
