"""Preview-first mail outbox. No external delivery without explicit allowlisting."""

import html
import os
import re
import smtplib
import ssl
import time
import uuid
from email.message import EmailMessage
from pathlib import Path

from sqlalchemy import select

from pharma_suite.automation.schema import alerts, emails, mail_events
from pharma_suite.automation.storage import atomic_write, digest, safe_artifact
from pharma_suite.quality.store import lock, now


def mail_settings():
    mode = os.getenv("MAIL_MODE", "preview")
    if mode not in {"preview", "smtp"}:
        raise ValueError("MAIL_MODE must be preview or smtp")
    recipients = [
        v.strip()
        for v in os.getenv("SMTP_RECIPIENTS", "reviewer@synthetic.invalid").split(",")
        if v.strip()
    ]
    sender = os.getenv("SMTP_FROM", "nivara@synthetic.invalid")
    for address in [sender, *recipients]:
        if not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", address):
            raise ValueError("Invalid mail address")
    if not recipients:
        raise ValueError("At least one recipient is required")
    return mode, sender, recipients


def prepare_email(engine, run_id, config, report=None, failure=None):
    with engine.begin() as conn:
        lock(conn)
        existing = (
            conn.execute(select(emails).where(emails.c.execution_id == run_id)).mappings().first()
        )
        if existing:
            return existing["id"]
        changed = (
            conn.execute(
                select(alerts)
                .where(alerts.c.revision > alerts.c.notified_revision)
                .order_by(alerts.c.id)
            )
            .mappings()
            .all()
        )
        mode, sender, recipients = mail_settings()
        subject = "[SYNTHETIC] Nivara distribution briefing — " + (
            "workflow failure" if failure else "report ready"
        )
        lines = [
            "NIVARA / PHARMA AUTOMATION DESK",
            "SYNTHETIC BUSINESS DATA ONLY",
            "",
            f"Workflow: {run_id}",
            "",
        ]
        if report:
            summary = report["summary_json"]
            lines += [
                f"Reporting window: {summary['start']} — {summary['end']}",
                f"Net sales revenue: INR {summary['revenue']}",
                f"Units distributed: {summary['units']}",
                f"Closing stock at cost: INR {summary['stock_value']}",
                f"Quality: {summary['quality_score']}%; {summary['quality_findings']} findings",
                f"Report ID: {report['id']}",
                "",
            ]
        if failure:
            lines += [f"Workflow failed: {failure}. Inspect persisted execution history.", ""]
        lines += [f"Changed alert conditions: {len(changed)}"]
        lines += [
            f"#{row['id']} [{row['severity']}/{row['status']}] {row['reason']}" for row in changed
        ]
        lines += [
            "",
            "Unchanged alert conditions are not re-notified.",
            "Source dates and snapshot assumptions are in the workbook. This "
            "is not validated clinical or regulatory reporting.",
        ]
        body = "\n".join(lines)
        message = EmailMessage()
        email_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "nivara-email:" + run_id))
        message["Subject"] = subject
        message["From"] = sender
        message["To"] = ", ".join(recipients)
        message["Message-ID"] = f"<{email_id}@synthetic.invalid>"
        message["Date"] = now().strftime("%a, %d %b %Y %H:%M:%S +0000")
        message.set_content(body)
        message.add_alternative(
            '<html><body style="font-family:Arial;color:#255f50">'
            "<h1>Nivara distribution briefing</h1><p><strong>SYNTHETIC DATA ONLY</strong></p>"
            '<div style="white-space:pre-wrap">' + html.escape(body) + "</div></body></html>",
            subtype="html",
        )
        if report and config.attach_report:
            artifact = safe_artifact(config, report["filename"], report["sha256"])
            message.add_attachment(
                artifact.read_bytes(),
                maintype="application",
                subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                filename=report["filename"],
            )
        filename = f"synthetic_{email_id}.eml"
        path = Path(config.report_dir) / filename
        atomic_write(path, lambda temporary: temporary.write_bytes(message.as_bytes()))
        conn.execute(
            emails.insert().values(
                id=email_id,
                execution_id=run_id,
                filename=filename,
                sha256=digest(path),
                subject=subject,
                body_text=body,
                recipients_json=recipients,
                status="preview" if mode == "preview" else "queued",
                attempts=0,
                created_at=now(),
            )
        )
        for row in changed:
            conn.execute(
                alerts.update()
                .where(alerts.c.id == row["id"])
                .values(notified_revision=row["revision"])
            )
        conn.execute(
            mail_events.insert().values(
                email_id=email_id,
                attempt=0,
                status="preview_created" if mode == "preview" else "queued",
                occurred_at=now(),
            )
        )
    return email_id


def delivery_policy(recipients):
    host = os.getenv("SMTP_HOST", "localhost")
    local = host in {"localhost", "127.0.0.1", "::1", "mailpit"}
    external = os.getenv("SMTP_ALLOW_EXTERNAL", "false").lower() == "true"
    allowed = {v.strip() for v in os.getenv("SMTP_ALLOWED_RECIPIENTS", "").split(",") if v.strip()}
    if not set(recipients) <= allowed:
        raise ValueError("SMTP recipients must be explicitly allowlisted")
    if not external and (
        not local
        or any(not address.endswith((".invalid", ".test", ".example")) for address in recipients)
    ):
        raise ValueError("External SMTP delivery is disabled")
    tls = os.getenv("SMTP_TLS", "starttls")
    if tls not in {"starttls", "ssl", "none"} or (tls == "none" and not local):
        raise ValueError("External SMTP requires TLS")
    return host, int(os.getenv("SMTP_PORT", "587")), tls


def deliver(engine, email_id, config):
    mode, _, _ = mail_settings()
    with engine.begin() as conn:
        lock(conn)
        row = conn.execute(select(emails).where(emails.c.id == email_id)).mappings().first()
        if not row:
            raise ValueError("Unknown email")
        if row["status"] in {"sent", "uncertain", "failed"}:
            return row["status"]
        if mode == "preview" or row["status"] == "preview":
            return "preview"
        if row["status"] == "sending":
            conn.execute(emails.update().where(emails.c.id == email_id).values(status="uncertain"))
            return "uncertain"
        host, port, tls = delivery_policy(row["recipients_json"])
        artifact = safe_artifact(config, row["filename"], row["sha256"])
        maximum = int(os.getenv("SMTP_MAX_ATTEMPTS", "3"))
        if not 1 <= maximum <= 5:
            raise ValueError("SMTP_MAX_ATTEMPTS must be 1–5")
        conn.execute(emails.update().where(emails.c.id == email_id).values(status="sending"))
    from email import policy
    from email.parser import BytesParser

    message = BytesParser(policy=policy.default).parsebytes(artifact.read_bytes())
    status = "failed"
    for attempt in range(1, maximum + 1):
        sending = False
        error = None
        try:
            factory = smtplib.SMTP_SSL if tls == "ssl" else smtplib.SMTP
            options = {"context": ssl.create_default_context()} if tls == "ssl" else {}
            with factory(host, port, timeout=10, **options) as server:
                if tls == "starttls":
                    server.starttls(context=ssl.create_default_context())
                username = os.getenv("SMTP_USERNAME")
                if username:
                    server.login(username, os.getenv("SMTP_PASSWORD", ""))
                sending = True
                refused = server.send_message(message, to_addrs=row["recipients_json"])
                # A partially accepted recipient set cannot safely be retried as a whole.
                status = "uncertain" if refused else "sent"
        except (OSError, smtplib.SMTPException) as exc:
            error = type(exc).__name__
            if isinstance(exc, smtplib.SMTPResponseException):
                retryable = 400 <= exc.smtp_code < 500
                status = "queued" if retryable and attempt < maximum else "failed"
            elif sending:
                status = "uncertain"
            else:
                status = "queued" if attempt < maximum else "failed"
        with engine.begin() as conn:
            conn.execute(
                mail_events.insert().values(
                    email_id=email_id,
                    attempt=attempt,
                    status=status,
                    error_type=error,
                    occurred_at=now(),
                )
            )
            conn.execute(
                emails.update()
                .where(emails.c.id == email_id)
                .values(
                    status="sending" if status == "queued" else status,
                    attempts=row["attempts"] + attempt,
                    error_type=error,
                    delivered_at=now() if status == "sent" else None,
                )
            )
        if status != "queued":
            return status
        time.sleep(config.retry_delay_seconds)
    return status
