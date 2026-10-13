"""Stable operational alert identities; changes and reviews retain audit history."""

from sqlalchemy import select

from pharma_suite.automation.schema import alert_events, alerts, executions
from pharma_suite.quality.schema import runs as quality_runs
from pharma_suite.quality.store import fingerprint, lock, now, review_identity
from pharma_suite.schema import tables


def audit_alert(conn, alert_id, action, actor, notes, before=None, after=None):
    conn.execute(
        alert_events.insert().values(
            alert_id=alert_id,
            action=action,
            actor=actor,
            notes=notes,
            before_json=before,
            after_json=after,
            occurred_at=now(),
        )
    )


def candidates(conn, config):
    result = {}

    def add(identity, kind, severity, reason, ids):
        result[identity] = {"kind": kind, "severity": severity, "reason": reason, "record_ids": ids}

    batch_rows = (
        conn.execute(
            select(
                tables["batches"],
                tables["inventory"].c.quantity,
                tables["inventory"].c.snapshot_date,
                tables["inventory"].c.is_sellable,
            ).join(tables["inventory"], tables["inventory"].c.batch_id == tables["batches"].c.id)
        )
        .mappings()
        .all()
    )
    totals = {}
    for row in batch_rows:
        key = (row["medicine_id"], row["warehouse_id"])
        totals[key] = totals.get(key, 0) + row["quantity"]
        remaining = (row["expiry_date"] - row["snapshot_date"]).days
        if row["quantity"] > 0 and 0 <= remaining <= config.near_expiry_days:
            add(
                f"expiry:{row['id']}",
                "near_expiry",
                "warning",
                f"Batch {row['batch_number']} holds {row['quantity']} units; "
                f"expires in {remaining} days "
                f"relative to snapshot {row['snapshot_date']}",
                {"batch_id": row["id"]},
            )
        if row["quantity"] > 0 and remaining < 0 and row["is_sellable"] is True:
            add(
                f"sellable:{row['id']}",
                "expired_sellable",
                "critical",
                f"Expired batch {row['batch_number']} is marked sellable at its stock snapshot",
                {"batch_id": row["id"]},
            )
    for (medicine, warehouse), quantity in totals.items():
        if quantity < config.low_stock_units:
            add(
                f"low:{medicine}:{warehouse}",
                "low_stock",
                "warning",
                f"Medicine {medicine} in warehouse {warehouse}: {quantity} units < "
                f"{config.low_stock_units} threshold",
                {"medicine_id": medicine, "warehouse_id": warehouse},
            )
    latest = {}
    current_production = None
    for run in conn.execute(select(quality_runs).order_by(quality_runs.c.id)).mappings():
        latest[run["dataset"]] = run
        if run["dataset"].startswith("production-"):
            current_production = run["dataset"]
    for dataset, run in latest.items():
        if dataset.startswith("production-") and dataset != current_production:
            continue
        for finding in run["report_json"].get("findings", []):
            if finding["severity"] == "critical":
                identity = "quality:" + fingerprint(
                    [
                        dataset,
                        finding["rule_id"],
                        finding["rule_version"],
                        finding["entity"],
                        finding["record_ref"],
                        finding["field"],
                    ]
                )
                add(
                    identity,
                    "critical_quality",
                    "critical",
                    finding["description"],
                    {
                        "dataset": dataset,
                        "rule_id": finding["rule_id"],
                        "record_ref": finding["record_ref"],
                    },
                )
    terminal = {}
    for run in conn.execute(
        select(executions)
        .where(executions.c.status.in_(["succeeded", "failed", "timed_out"]))
        .order_by(executions.c.completed_at)
    ).mappings():
        terminal[run["kind"]] = run
    for kind, run in terminal.items():
        if run["status"] != "succeeded":
            add(
                "workflow:" + kind,
                "workflow_failure",
                "error",
                f"{kind} workflow {run['id']} {run['status']}: {run['error_type']}",
                {"execution_id": run["id"]},
            )
    return result


def evaluate_alerts(engine, config):
    changes = []
    with engine.begin() as conn:
        lock(conn)
        active = candidates(conn, config)
        existing = {row["identity"]: row for row in conn.execute(select(alerts)).mappings()}
        timestamp = now()
        for identity, value in active.items():
            digest = fingerprint(value)
            old = existing.get(identity)
            if old is None:
                alert_id = conn.execute(
                    alerts.insert().values(
                        identity=identity,
                        **value,
                        content_hash=digest,
                        revision=1,
                        notified_revision=0,
                        status="new",
                        detected_at=timestamp,
                        last_seen_at=timestamp,
                    )
                ).inserted_primary_key[0]
                audit_alert(conn, alert_id, "new", "alert-engine", value["reason"], after=value)
                changes.append(alert_id)
            elif old["content_hash"] != digest or old["status"] == "resolved":
                conn.execute(
                    alerts.update()
                    .where(alerts.c.id == old["id"])
                    .values(
                        **value,
                        content_hash=digest,
                        revision=old["revision"] + 1,
                        status="new",
                        last_seen_at=timestamp,
                        resolved_at=None,
                    )
                )
                audit_alert(
                    conn,
                    old["id"],
                    "reopened" if old["status"] == "resolved" else "changed",
                    "alert-engine",
                    value["reason"],
                    {"status": old["status"]},
                    value,
                )
                changes.append(old["id"])
            else:
                conn.execute(
                    alerts.update().where(alerts.c.id == old["id"]).values(last_seen_at=timestamp)
                )
        for identity, old in existing.items():
            if identity not in active and old["status"] != "resolved":
                conn.execute(
                    alerts.update()
                    .where(alerts.c.id == old["id"])
                    .values(status="resolved", revision=old["revision"] + 1, resolved_at=timestamp)
                )
                audit_alert(
                    conn,
                    old["id"],
                    "resolved",
                    "alert-engine",
                    "Condition no longer detected",
                    {"status": old["status"]},
                    {"status": "resolved"},
                )
                changes.append(old["id"])
    return changes


def acknowledge(engine, alert_id, actor, notes):
    review_identity(actor, notes)
    with engine.begin() as conn:
        lock(conn)
        row = conn.execute(select(alerts).where(alerts.c.id == alert_id)).mappings().first()
        if not row:
            raise ValueError("Unknown alert")
        if row["status"] == "resolved":
            raise ValueError("Resolved alerts cannot be acknowledged")
        if row["status"] != "acknowledged":
            conn.execute(
                alerts.update().where(alerts.c.id == alert_id).values(status="acknowledged")
            )
            audit_alert(
                conn,
                alert_id,
                "acknowledged",
                actor,
                notes,
                {"status": row["status"]},
                {"status": "acknowledged"},
            )
