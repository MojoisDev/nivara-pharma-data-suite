# Pharmaceutical data quality engine — Phase 2

All sources are synthetic. This is an inspectable portfolio workflow, not a validated GxP, FDA-compliant or clinical decision system. Phase 1 sales and inventory analytics remain available.

## Architecture

```mermaid
flowchart LR
  G[Fixed-seed Phase 1 generator] --> C[Clean synthetic envelope]
  C --> F[Explicit fault injections + independent manifest]
  C --> S[(Raw staging JSON)]
  F --> S
  S --> V[Versioned rules + configured assessment clock]
  V --> R[(Runs + findings + deduplicated issues)]
  V --> Q[Quarantine flags]
  R --> D[Streamlit quality desk + CSV]
  Q --> M[Manual correction + audit + revision]
  M --> V
  V --> A[Zero findings + same revision + explicit approval]
  A --> P[(Constrained Phase 1 PostgreSQL tables)]
  P --> B[Existing sales and inventory desk]
```

`quality/models.py` validates the envelope and configuration with Pydantic; raw rows deliberately remain permissive so malformed business data can be staged. `engine.py` evaluates data without database writes. `rules.py` is the stable catalog. `demo.py` owns explicit fault injection and an independent expected-finding manifest. `store.py` persists lifecycle changes transactionally. `cli.py` exposes controlled operations. The dedicated native Streamlit page reads stored runs rather than recomputing scores on navigation.

## Schema and migration

`pharma init` automatically applies the additive migration. For PostgreSQL initialized using raw SQL, apply `sql/001_foundation.sql` first on a new database, then `sql/002_data_quality.sql` with `psql -v ON_ERROR_STOP=1 -f ...`. Migration 002 is safe to repeat and does not delete existing data.

Three nullable columns extend existing tables: `medicines.manufacturer`, `distributors.contact_email`, and `inventory.is_sellable`. Existing values remain NULL until explicitly reviewed. The staging contract requires manufacturer and sellability; contact email is validated when supplied. Staging additionally carries declared medicine, line total and invoice total, while production retains the original normalized Phase 1 model.

| Table | Purpose |
| --- | --- |
| dq_schema_migrations | Applied additive schema version |
| dq_datasets | Source name, revision, content hash, envelope metadata and lifecycle status |
| dq_staging_records | Stable source reference, raw payload, quarantine and reviewed tombstone flags |
| dq_validation_runs | Immutable report snapshot, configuration, source revision/hash, assessment and detection clocks |
| dq_issues | Unique fingerprint, rule/version, entity/reference/field, severity, description, remediation, first/last run, status and notes |
| dq_run_findings | Unique run/issue observation pair |
| dq_audit_events | Actor, action, notes, timestamp and before/after evidence |

Foreign keys connect datasets, runs, issues and observations. Unique constraints prevent duplicate staging identities, issue fingerprints and run observations. Indexes support dataset, run and status lookups. Malformed rows live only in raw staging; production keys and quantity/date constraints remain active.

## Rule catalog

All rules below are version **1.0**. IDs remain stable; change the version when semantics change. Default thresholds and all six weights are in `config/quality.json`. Required fields, FK relationships and business keys are explicit in `rules.py`.

| ID | Dimension | Severity | Check | Suggested remediation |
| --- | --- | --- | --- | --- |
| CMP001 | completeness | error | Required field is missing or blank | Confirm the value with the synthetic source; supply an explicit audited correction. |
| CMP002 | completeness | critical | Required entity has no records | Restore the complete feed; partial snapshots cannot be approved. |
| UNI001 | uniqueness | critical | Duplicate primary identifier | Review both copies; explicitly tombstone the erroneous row or correct its ID. |
| UNI002 | uniqueness | error | Duplicate business reference | Review the business reference; no automatic renumbering. |
| UNI003 | uniqueness | error | Batch number violates the production global namespace | Use an explicitly reviewed global batch reference compatible with Phase 1. |
| VAL001 | validity | error | Date must be a real ISO YYYY-MM-DD date | Confirm and explicitly correct the date; never infer a manufacturing or expiry date. |
| VAL002 | validity | critical | Quantity must be an integer in the permitted range | Reconcile units against the source; negative closing inventory is not permitted. |
| VAL003 | validity | error | Price must be finite, positive, within bounds and at most two decimal places | Review the source currency and amount; do not automatically change prices. |
| VAL004 | validity | error | Identifier must be a positive integer | Review the identifier and dependent references manually. |
| VAL005 | validity | warning | Contact email format is invalid | Correct the contact from a synthetic source; no external email is sent. |
| VAL006 | validity | error | Batch reference format is invalid | Review the lot reference; expected 3–30 uppercase alphanumeric/hyphen characters. |
| VAL007 | validity | error | Region is outside the configured Indian region set | Use North, South, East or West after source review. |
| VAL008 | validity | error | Sellability must be a boolean | Explicitly review availability; unknown is not treated as sellable. |
| VAL009 | validity | warning | Selling price exceeds the configured list-price ceiling | Review contract pricing; discounts are allowed and differing prices alone are not errors. |
| REF001 | referential integrity | critical | Referenced entity does not exist in staging | Restore the parent or explicitly correct the reference before approved load. |
| CON001 | consistency | critical | Expiry must be strictly after manufacturing | Review original dates; never infer a new expiry. |
| CON002 | consistency | error | Receipt date is incompatible with manufacturing or expiry | Review receipt and batch dates against the source. |
| CON003 | consistency | critical | Sale predates manufacturing | Review the sale and batch association and source dates. |
| CON004 | consistency | critical | Sale predates the batch receipt | Reconcile the chronological movement history. |
| CON005 | consistency | critical | Sale occurs after batch expiry | Quarantine the sale for explicit review; expiry-day sales are allowed by this model. |
| CON006 | consistency | critical | Sale line, invoice and batch warehouses disagree | Review the allocation; transfers are not modeled. |
| CON007 | consistency | critical | Declared medicine does not match the batch medicine | Review both identifiers; never substitute an ID automatically. |
| CON008 | consistency | error | Declared line total differs from quantity times unit price | Reconcile the declared amount with the synthetic source. |
| CON009 | consistency | error | Invoice total differs from calculated line totals | Review all invoice lines, discounts and source totals. |
| CON010 | consistency | critical | Expired stock is marked sellable | Explicitly mark expired stock unavailable; expired held inventory is legitimate. |
| CON011 | consistency | critical | Closing inventory contradicts receipts and sales | Reconcile movements; no silent stock balancing adjustment. |
| CON012 | consistency | critical | Chronological sales exceed batch receipt units | Review oversold lines against available stock and receipt dates. |
| CON013 | consistency | error | Transaction or inventory snapshot is incompatible with the declared snapshot | Review the feed cutoff and snapshot date; do not silently move dates. |
| CON014 | consistency | error | Distributor and warehouse regions differ | Review distributor assignment; cross-region fulfillment is not modeled in Phase 1. |
| CON015 | consistency | error | Invoice has no sale lines | Restore the missing lines or explicitly reject the invoice. |
| CON016 | consistency | error | Batch lacks its inventory snapshot | Restore its closing position; partial snapshots cannot be approved. |
| TIM001 | timeliness | warning | Import timestamp is missing, malformed, future-dated or older than threshold | Review the feed delivery timestamp; replay uses an explicit historical clock. |
| TIM002 | timeliness | warning | Reporting feed date is missing, invalid, future-dated or delayed | Review the last reported business date and feed lag. |

Batch identity follows the existing global production namespace, with an additional warehouse-scoped duplicate check. Duplicate checks flag every copy, including the first. Sales may occur on the expiry date, but never afterwards. Expired stock can legitimately remain in inventory when marked unavailable. Transfers, returns, replenishment beyond modeled receipts, tax and clinical product regulation are not modeled. Inventory reconciliation uses receipt units less valid, in-snapshot sales; cumulative checks use chronological sale dates against the receipt. Missing or ambiguous parents disable dependent calculations rather than manufacturing additional findings from guessed relationships.

Default bounds: unit prices greater than zero and at most INR 100,000, two decimal places; quantities integer up to 1,000,000 (closing stock permits zero, receipts and sold units require positive values); sale price ceiling 1.2 × medicine list price. This ceiling is a review warning, not a claim about Indian pricing law. Regions are North/South/East/West. Batch reference is 3–30 uppercase alphanumeric/hyphen characters. Dates must be real ISO dates, identifiers positive integers, and availability a boolean.

## Scoring contract

For each dimension, **score = 100 × (eligible checks − failed checks) / eligible checks**. An eligible check is one evaluated rule/record/field opportunity, not one source record. Required-cell checks plus entity-presence checks form completeness. Duplicate primary/business/batch checks form uniqueness. Other dimensions count their respective evaluable opportunities. Per-rule denominators and dimension aggregates are persisted with the report.

Multiple rules can fail for the same row, and each failure counts in its dimension. Invalid prerequisite values or ambiguous parent rows make dependent checks not applicable; those checks are reported separately and excluded from the denominator. A dimension without eligible checks is N/A. An entirely empty source is not perfect: required-entity checks fail. Overall score is the weighted mean of applicable dimension scores, renormalizing over applicable nonzero weights; it is N/A if none remain. All six weights must be finite and nonnegative with positive total. Default weights are equal, so complete failure of the two timeliness checks contributes one sixth of the overall result even when row-level scores remain high.

Passing/failing record counts use distinct active staging references. A row failing three rules counts once as a failing row. Feed metadata and missing-entity findings affect scores and severity totals, but do not fabricate source-row failures. Severity counts are findings, not distinct records. A high aggregate score never overrides the approval gate: **every finding, including warnings or manually labeled false positives, blocks approval**.

Timeliness defaults: received age ≤24 hours and business feed lag ≤2 calendar days, with no future timestamps. The demo explicitly assesses against **2026-01-01T12:00:00Z**, replaying the 2025 feed. Actual detection timestamps are separate. This does not claim the feed is fresh today. Use `--as-of` with an explicit current clock when demonstrating current freshness; that creates a new persisted run, not a rewrite of old history.

## Lifecycle and audit behavior

1. Stage a synthetic envelope. Identical repeated staging is a no-op. A different payload under the same name is rejected; use another source name or an audited correction.
2. Validate the current revision. Persist the run, issue transitions, observations, quarantine flags and audit evidence in one transaction. PostgreSQL advisory locking serializes suite writers. A database failure rolls everything back.
3. Issue identity is the hash of dataset, rule/version, entity, stable source reference and field. Repeated failures become persistent observations; absent failures resolve automatically; a resolved issue that fails again reopens. Historical runs retain their original findings and scores.
4. Review with an actor and notes. `acknowledged`, `resolved` or `false_positive` labels do not alter source values or remove a failing check. A manually resolved issue reopens if it still fails. Reviewer labels are local audit attribution, not authenticated electronic signatures.
5. Correct only explicitly supplied JSON fields, or explicitly tombstone a reviewed duplicate. Original payload remains in audit evidence. Stable ordinal references survive edits/tombstones. Expected revision protects against stale changes. Corrections invalidate prior approval and require revalidation. Dataset metadata can be reviewed with entity `__metadata__` and reference `metadata`.
6. Approve only a zero-finding, hash-matching latest run for the exact current revision. Entire snapshots are gated; valid siblings of quarantined records are not partially loaded. Existing production IDs and business values must agree. Conflicts abort before mutation. New IDs may be inserted; existing NULL manufacturer/email/sellability may be filled only by explicit approval and are audited individually. Existing non-NULL values, dates, identifiers, prices and stock are never silently overwritten. Repeat approval adds no duplicate business records.

The application only appends audit events. A database administrator can alter them: no tamper-evident storage, external authentication, regulated validation or electronic-signature certification is claimed. Structured logs identify lifecycle events without connection credentials.

## Commands

From the repository root with the virtual environment active and DATABASE_URL configured:

```bash
pharma init
pharma seed                         # Seeds only if all eight business tables are empty.
pharma dq generate
pharma dq stage --file data/quality/demo-clean.json
pharma dq validate --dataset demo-clean --config config/quality.json
pharma dq validate --dataset demo-corrupted
pharma dq verify-manifest
pharma dq report --dataset demo-corrupted > data/quality/corrupted-report.json
streamlit run dashboard/app.py --server.address=127.0.0.1
```

Equivalent module command: `python -m pharma_suite.quality.cli validate --dataset demo-corrupted`. Built-in demos stage automatically only when absent; validation never overwrites an edited source. `report --run-id ID` selects historical evidence. Unknown datasets and invalid configuration fail nonzero with structured errors.

Review a finding using the actual issue ID from the report/dashboard:

```bash
pharma dq issue --id 1 --status acknowledged --actor portfolio-reviewer --notes 'Reviewed source; correction pending'
pharma dq correct --dataset demo-corrupted --entity medicines --record medicines:4 --expected-version 1 --patch '{"name":"Reviewed synthetic medicine"}' --actor portfolio-reviewer --notes 'Explicit source correction'
pharma dq validate --dataset demo-corrupted
pharma dq approve --dataset demo-clean --expected-version 1 --actor portfolio-reviewer --notes 'Reviewed zero-finding snapshot'
```

The example correction illustrates syntax, not a repair of all injected faults. Use the actual failing reference and current revision; never blindly infer new dates or amounts. `--delete` replaces `--patch` for a reviewed tombstone. Revalidating altered demos will intentionally differ from the original ground-truth manifest. Generate a new source name to repeat an untouched fault experiment.

`pharma ingest` remains the original **explicit full refresh** for a dedicated Phase 1 synthetic environment. It is not the Phase 2 approved-load command. Container startup now uses `pharma seed`, preserving existing business data and quality history. No reset is required for upgrade.

## Deterministic demonstration and executed evidence

The full clean source has 44,365 records. The corrupted source has 44,366, including a duplicate medicine. Faults cover duplicate IDs/SKUs, missing name/manufacturer, orphan category, negative price and stock, invalid expiry chronology, malformed receipt date, incorrect line/invoice totals, expired sellable stock, email format and delayed import/feed. The independent manifest lists exact expected rule/version/entity/reference/field tuples. Parent FK failures must be caught in staging because constrained production insertion would reject them.

Executed against PostgreSQL: clean **100%**, zero findings and zero failed records; corrupted **83.33178580049045%**, **19 findings** across **13 failing records**, with 7 critical, 9 error and 3 warning findings. Expected **19**, detected **19**, missing **0**, unexpected **0**. A second corrupted run records 19 persistent, zero new issues. Clean approval preserves Phase 1 table counts and business amounts, filling only reviewed nullable metadata. See `docs/verification_phase2.json` for actual persisted evidence and final test details.

The quality page includes score/check denominators, assessment/detection clocks, prior-run comparison, trend, current severity workload, filterable selected-run findings with current statuses, medicine/batch/entity and cross-dataset distribution, raw failed source evidence, suggested actions, reviewed status changes, audit events and filtered CSV export. Revalidation is explicit; approval and source correction use the CLI.

## Tests and troubleshooting

```bash
pytest -q
TEST_DATABASE_URL=postgresql+psycopg://pharma:synthetic_local_only@localhost:55432/pharma_test pytest -q
ruff check .
ruff format --check .
```

Use a separate disposable test database. Phase 1 integration tests refresh its core tables; Phase 2 PostgreSQL tests use isolated temporary schemas. Tests include hand-verified fixtures, individual rules, scoring and N/A behavior, both duplicate copies, historical clocks, expired held versus sellable stock, exact fault expectations, lifecycle reopening/resolution, explicit tombstones, false-positive gating, stale revisions, production conflicts, idempotency and injected database-trigger failures proving transaction rollback. Streamlit AppTest exercises stored quality runs and original sales filters.

If quality sources are absent, run the two validate commands. If a source changed, revalidate rather than using an old score. If approval fails, inspect the findings or production conflict and make an explicit source correction; do not disable constraints. Existing Phase 1 Docker health checks and environment configuration remain applicable. Without PostgreSQL, `DATABASE_URL=sqlite:///data/pharma_demo.db` supports portable validation and UI checks, but does not prove PostgreSQL integration. See README troubleshooting for recovery commands.

## Pharmaceutical use cases and next integration points

Demonstrates distributor-feed reconciliation, batch expiry/availability review, invoice and stock consistency, missing master data, and incoming-source quarantine before analytics publication. It does not evaluate patient safety, drug efficacy, statutory price compliance, cold-chain telemetry or product authenticity.

Recommended Phase 3 integration points, not implemented: invoke the CLI in a scheduler with an explicit current assessment clock; consume stored runs/issues for approved reporting; use audit/run IDs as report provenance; add authenticated reviewer roles and migration governance before multi-user adoption. There is no FastAPI architecture in Phase 1, so no API framework was added. Scheduled reporting and email automation remain outside this phase.

## Implementation file inventory

Created: `src/pharma_suite/quality/{__init__,models,rules,engine,demo,schema,migrations,store,cli}.py`, `dashboard/pages/2_Data_Quality.py`, `tests/test_quality.py`, `tests/test_quality_transactions.py`, `tests/test_quality_dashboard.py`, `sql/002_data_quality.sql`, `config/quality.json`, `data/quality/{demo-clean,demo-corrupted,fault_manifest}.json`, this document, `docs/verification_phase2.json`, and `docs/screenshots/{quality-desk,quality-ledger}.jpg`.

Modified: core `src/pharma_suite/{schema,db,generate,cli}.py`, `pyproject.toml`, `requirements.lock`, `Dockerfile`, `scripts/start.sh`, Phase 1 generated CSV metadata/manifest, `README.md`, and `docs/ARCHITECTURE.md`. Existing Compose ports, health checks, environment configuration and Phase 1 queries/analytics remain applicable.
