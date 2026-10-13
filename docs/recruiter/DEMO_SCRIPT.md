# Demonstration script — 2 minutes 30 seconds

The rendered [video](nivara-demo.mp4) is a silent, captioned walkthrough of nine real local dashboard captures. It is not a continuous screen recording and does not simulate clicks, new workflow execution, or delivery. Use the text below as a spoken script for a personal version.

## Spoken walkthrough

### 0:00–0:20 · 01 / THE PROJECT

Nivara connects synthetic pharmaceutical sales, inventory, data quality, and reporting. Python and PostgreSQL power 24 months of data across four Indian regions and 120 medicines.

Screen: `01-sales.jpg`.

### 0:20–0:38 · 02 / INVENTORY CORRECTNESS

Stock is reconstructed from receipts less historical sales. Expiry exposure uses the reporting date; values are acquisition cost. Separate batch facts prevent sale lines from multiplying stock.

Screen: `02-inventory.jpg`.

### 0:38–0:50 · 03 / THE CLEAN BASELINE

Thirty-three versioned rules cover six quality dimensions. The clean synthetic demo scores 100 percent under its declared historical replay clock.

Screen: `03-quality-clean.jpg`.

### 0:50–1:08 · 04 / DELIBERATE SOURCE FAILURES

The corrupted demo detects 19 findings across 13 failing records. Its 83.33 percent score weights quality dimensions; it is not simply a percentage of clean rows.

Screen: `04-quality-corrupted.jpg`.

### 1:08–1:25 · 05 / TRACEABLE REVIEW

The ledger retains source references, rule identifiers, severity, and issue status. Corrections require reviewer notes and revision checks. Status changes never silently repair source data.

Screen: `05-quality-ledger.jpg`.

### 1:25–1:45 · 06 / ONE DEDICATED SCHEDULER

A dedicated scheduler chains validation, analytics, reporting, alerts, and email preparation. PostgreSQL locks and request keys prevent overlapping controllers and duplicate requests. Attempts and outcomes are persisted.

Screen: `06-workflows.jpg`.

### 1:45–2:00 · 07 / ACTIONABLE CONDITIONS

Alerts track stock, expiry, critical quality findings, and workflow failures. Reviewers can acknowledge conditions; resolved and changed conditions retain audit history. Unchanged revisions do not create repeated notification summaries.

Screen: `07-alerts.jpg`.

### 2:00–2:16 · 08 / REPORT EVIDENCE

The seven-sheet annual workbook was checked against independent PostgreSQL totals: INR 54,539,450.97 revenue and INR 70,823,412.56 closing stock value. Downloads verify registered file checksums.

Screen: `08-reports.jpg`.

### 2:16–2:30 · 09 / VERIFIED SCOPE

Email stays in local preview mode. The latest full suite passed all 92 tests, including PostgreSQL integration tests. This is a synthetic portfolio demonstration, not validated clinical or regulatory software.

Screen: `09-mail.jpg`.

## Record your own version

1. Open the local dashboard at `http://127.0.0.1:8502/` and use a desktop-sized browser. Keep credentials and terminals containing environment variables out of the capture.
2. Start your preferred Linux screen recorder and microphone. Read the script at a natural pace; shorten sentences if needed.
3. Show sales and inventory, compare the clean and corrupted quality sources, open the review ledger, then show workflow schedules, alerts, annual report metadata, and local preview mail.
4. Use existing records for a predictable demo. If demonstrating a new workflow, explicitly confirm a synthetic request and wait for its real status; never edit a screenshot to imply success.
5. Keep `MAIL_MODE=preview`. State that historical inventory is a snapshot and the application is not validated clinical or regulatory software.
6. Preview the recording for readable labels, accurate claims, and clear audio before publishing.

## Rebuild the captioned video

From the repository root, with ffmpeg and ffprobe installed:

```bash
.venv/bin/python docs/recruiter/render_demo.py
```

The renderer asserts a 150-second H.264 1920×1080 output. Captures are in `demo-captures/`; encoding metadata is in `demo_metadata.json`. The output is approximately 1.9 MB. No external account is needed.

## Technical notes to retain

The source review found an SMTP cleanup retry defect; do not describe email as exactly once or enable real delivery for the demo. The 92 passing tests are functional verification, not a production-load benchmark. No personal voice narration or interactive interview performance has been recorded in this pass.
