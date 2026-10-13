# Architecture and technical-decision practice

## A 45-second opening

> Nivara is my Python and PostgreSQL portfolio project for pharmaceutical distribution analytics. I used synthetic data covering two years, four Indian regions, and 120 medicines. The application has three parts: sales and inventory intelligence, audited data-quality review, and scheduled Excel reporting. I focused on preventing double-counted stock, keeping money calculations exact, and making workflow failures traceable. A dedicated scheduler runs bounded workers, while the dashboard and authenticated local API expose results and manual requests. I verified the implementation with 92 tests, including PostgreSQL integration tests. It is a local portfolio simulation, with its production and clinical limits stated explicitly.

Adapt this to your natural speaking voice. Mention AI-assisted implementation if asked about authorship; be ready to explain the actual source and changes you reviewed.

## Decisions you should be able to defend

| Question | Answer grounded in this implementation | Source to open |
| --- | --- | --- |
| Why PostgreSQL? | Foreign keys and checks protect relationships; transactions protect writes; advisory locks coordinate local processes. SQLite remains a portable demo/test option. | `schema.py`, `db.py`, `automation/storage.py` |
| Why SQLAlchemy Core rather than an ORM? | The application mostly runs explicit relational queries and batch inserts. Core gives parameterized SQL and transactions without requiring object lifecycle management. | `db.py`, `analytics.py` |
| How do you avoid double-counting? | Sales facts have one row per sale line. Inventory facts have one row per batch. I aggregate them separately instead of joining batch stock onto every sale line. | `analytics.py` |
| How is money handled? | Database prices are two-decimal Numeric values. Analytics converts them to integer cents before multiplication and aggregation. Workbook presentation converts values for display. | `analytics.py`, `automation/reporting.py` |
| How is stock at a past date computed? | Include receipts by the reporting date and subtract all sales up to that date. Reject dates later than the stock snapshot. No transfers, returns, or disposal movements are modeled. | `build_report`, `docs/KPIS.md` |
| Why not opening/closing average for turnover? | Receipt waves make that shortcut misleading. The implementation integrates daily end-of-day inventory across the selected interval, then divides period COGS by that average. | `build_report`, `inventory_turnover.sql` |
| What does a quality score mean? | Each dimension uses failed and eligible checks, with dependent checks marked not applicable. The overall score weights dimensions; it is not simply the percentage of clean rows. | `quality/engine.py` |
| Why preserve bad staging data? | Keeping the raw record supports investigation and audited corrections. A revision change requires revalidation before approval; manual status changes do not fix the data. | `quality/store.py` |
| How do you prevent duplicate jobs? | One scheduler owns a PostgreSQL session lock. A second lock excludes overlapping controllers. Unique request keys plus request hashes prevent duplicate or conflicting submissions. | `automation/scheduler.py`, `workflow.py` |
| Why a subprocess timeout? | It provides a hard boundary around long-running work. The controller terminates the process group, records timeout status, and applies bounded retries. Linux parent-death protection limits orphan workers. | `workflow.py`, `worker.py` |
| Are report writes atomic with the database? | File replacement is atomic and registry writes are transactional, but there is no cross-resource transaction. A registry failure can leave an unregistered file; download routes use the registry and checksum, so that file is not automatically published. | `storage.py`, `reporting.py` |
| Is email exactly once? | No. SMTP acceptance and database updates cannot be one transaction. Ambiguous delivery needs reconciliation. The audit found an accepted-message/QUIT-error retry defect; preview mode is used until that is fixed. | `mail.py`, `SOURCE_REVIEW.md` |
| What changes for production? | Authenticated user roles, stronger deployment boundaries, retention, backups and recovery exercises, broader source contracts, observability, and larger-data query design. These are requirements to assess, not implemented features. | `docs/automation.md` |

## Three stories to rehearse

### Correctness: stock multiplication

**Situation:** A medicine batch can appear in many sale lines. Joining its stock quantity onto each line would inflate held units.  
**Decision:** Query sale-line and batch facts separately and reconstruct stock from receipts less historical sales.  
**Evidence:** The repeated-sales fixture checks stock is not multiplied; independent PostgreSQL queries match the dashboard and workbook.  
**Limit:** The model covers receipts and sales, not a complete ERP inventory movement ledger.

### Data quality: review without silent repair

**Situation:** A source can contain duplicate keys, invalid dates, broken relationships, or inconsistent quantities.  
**Decision:** Preserve raw staging records, detect findings with versioned rules, quarantine affected records, and require explicit correction and revalidation.  
**Evidence:** The corrupted demo contains 19 findings across 13 failing records. Tests ensure false-positive labels cannot bypass failed-data approval and that transaction failures roll back writes.  
**Limit:** Reviewer names are local labels, not verified identities or regulated electronic signatures.

### Reliability: duplicate requests and failures

**Situation:** A user retries a workflow request, or a worker fails after creating an artifact.  
**Decision:** Store requests with keys and hashes, freeze configuration, bound worker runtime, persist attempts, and verify registered artifacts on retry/download.  
**Evidence:** Repeated API requests returned the same execution ID; the deliberately invalid reporting window failed safely and the subsequent daily workflow succeeded.  
**Limit:** Scheduling is single-worker, misses are not backfilled, and SMTP delivery has no exactly-once guarantee.

## Rehearsal routine — 10 minutes

1. Explain the project in 45 seconds without reading the opening.
2. Draw generator → database → validation → analytics → report → alerts → preview, and distinguish the scheduler from the dashboard.
3. Open `build_report` and explain historical sales, integer cents, and the turnover denominator in 90 seconds.
4. Explain what happens when a worker times out, when a duplicate key is submitted, and when an SMTP outcome is uncertain.
5. Finish with one current limitation and one smallest next fix. Use the source audit, not a new feature roadmap.

Score each answer from 0–2: 0 = vague, 1 = mechanism explained, 2 = mechanism plus source evidence and limit. A strong answer is understandable before it becomes technical.

## Mock interview prompts

- Walk me through one invoice and its effect on stock and revenue.
- What prevents a sale line from referencing a batch in another warehouse?
- What would cause the quality score to change without changing the number of failing records?
- What happens if the scheduler restarts during a report?
- What does idempotency guarantee here, and what does it not guarantee?
- What do your tests prove about transactions? What do they not prove?
- Tell me about a bug your review found and the smallest test that would catch it.

For an interactive practice session, give a 45-second explanation and ask for feedback on correctness, clarity, and unsupported claims. Personal interview performance cannot be verified by a written guide alone.
