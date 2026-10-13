# Source review — Nivara

**Reviewed 13 October 2026.** This is a source audit, not a certification. Application code was not changed during this review.

What this repo does: Nivara models synthetic pharmaceutical distribution, calculates sales and stock metrics, validates staged data, and generates scheduled reports with alerts. The expected load is one trusted local operator, one scheduler, and the included 44,365-row business dataset.

## Must fix before real SMTP delivery

1. **A cleanup error can resend an already accepted email** (`src/pharma_suite/automation/mail.py:195–213`).
   - **What this is:** The mailer sends inside an SMTP context manager. Leaving that context sends QUIT to close the connection.
   - **Problem:** After `send_message` succeeds, a QUIT response of 421 enters the retryable-response branch and sends the whole message again. An isolated mocked probe confirmed two `send_message` calls and a final `sent` state. No real SMTP connection was opened; see [probe evidence](audit_probe.json).
   - **Fix:** Track whether DATA acceptance returned successfully separately from whether sending started. A cleanup error after acceptance must not trigger a resend; retain the accepted outcome and log cleanup failure. Add a test specifically for successful send followed by a failing `__exit__`, while preserving retries for rejected DATA.
   - **If we skip it:** Explicitly enabled real SMTP can send duplicate reports. Preview mode is unaffected and remains the demonstration mode.

## Should fix

2. **The foundation PostgreSQL fixture trusts any database URL** (`tests/test_postgres.py:15–23`, `src/pharma_suite/db.py:39–52`).
   - **What this is:** Integration tests use `TEST_DATABASE_URL` and perform complete synthetic business-table refreshes.
   - **Problem:** The fixture verifies only the PostgreSQL URL prefix. If an operator accidentally points it at the portfolio database, `ingest` deletes and replaces its business rows. The other transaction suites use isolated, generated schemas; this foundation suite does not.
   - **Fix:** Reuse the generated-schema fixture pattern from `tests/test_automation_transactions.py`, including an isolated connection search path and cleanup. This protects existing tables even if the URL points at a populated database.
   - **If we skip it:** A mistaken environment variable can reset business data. The documented disposable test database was used for this review; no portfolio data was overwritten.

## Strengths confirmed in actual source

- Sales-line facts and batch facts are queried separately. Inventory is not multiplied by sale-line joins.
- Money enters analytics as integer cents; KPI fixtures compare SQL results with Python calculations.
- Stock reconstruction includes historical sales, while turnover uses daily average end-of-day inventory. Reporting beyond the snapshot is rejected.
- Composite foreign keys constrain sale lines and batches to the same warehouse.
- Ingestion and quality review writes use transactions. Trigger-based tests confirm rollback behavior.
- Quality corrections require expected revisions and review notes. False-positive labels do not bypass approval; existing business values cannot be overwritten by approval.
- Consistent snapshots use PostgreSQL repeatable-read transactions. Missing import timestamps are reported rather than fabricated.
- Dedicated scheduler and worker locks are enforced through PostgreSQL session locks; requests survive application restarts.
- Worker subprocesses have bounded deadlines and Linux parent-death protection. Idempotency keys distinguish duplicate requests from changed requests.
- Artifact downloads resolve registered identifiers, verify directory containment, and compare SHA-256 hashes. XLSX text cells guard formula-leading input.
- API data and write routes require a token, configured ports bind to loopback, and SMTP credentials stay outside persisted workflow configuration.

## Verification and coverage

Fresh execution: **92 passed, 0 failed, 0 skipped in 14.92 seconds**, including PostgreSQL integration tests. Ruff lint and formatting passed. The initial attempt found a stopped dedicated test database: 82 tests passed and 10 setup errors occurred. Restarting the existing `pharma-phase1-db` container resolved those environment errors; the full suite was then rerun.

Read end to end: generation and ingestion, relational schema, analytics, quality evaluation/staging/correction/approval, bounded workflow execution, scheduler ownership, atomic storage, report generation, alert lifecycle, SMTP delivery, API authentication, and all three dashboard pages. Read deployment/configuration and representative tests, including hand fixtures and PostgreSQL rollback checks. Reviewed CLI entry points and quality CLI routing. The complete test suite ran; not every test assertion or descriptive rule-catalog entry received a separate line-by-line review.

Known boundaries are not hidden defects: trusted-local access, a single worker, no offline schedule backfill, historical inventory clocks, no returns/transfers/disposals, and locally attributed reviewer labels. Large historical tables are read into memory in several places; that fits the supplied local dataset, but requires retention/query redesign before sustained production scale.

**Verdict:** The core analytics and local workflow architecture are well supported by tests. It is suitable to demonstrate as a synthetic portfolio project with its limits stated. Address the SMTP retry defect before real delivery and isolate the foundation test fixture before broader contributor use.

**Not checked:** live SMTP, Microsoft Excel GUI, production load, penetration testing, disaster recovery, GitHub CI, or licensing of a future published repository. No unmeasured performance or commercial-impact claims are made.
