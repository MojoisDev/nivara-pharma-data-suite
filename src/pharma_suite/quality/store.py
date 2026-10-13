"""Transactional staging, issue lifecycle, reviewed edits and append-only approved loads."""

import hashlib
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select, text

from pharma_suite.generate import TABLE_ORDER
from pharma_suite.generate import validate as validate_foundation
from pharma_suite.quality.engine import evaluate, parse_date
from pharma_suite.quality.models import Bundle, QualityConfig, Report
from pharma_suite.quality.schema import audit, datasets, findings, issues, records, runs
from pharma_suite.schema import tables

log = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc)


def fingerprint(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def lock(conn):
    if conn.dialect.name == "postgresql":
        conn.execute(text("SELECT pg_advisory_xact_lock(71012025)"))


def review_identity(actor, notes):
    if not actor or not actor.strip() or not notes or not notes.strip():
        raise ValueError("A reviewer actor and nonempty resolution notes are required")
    if len(actor) > 100:
        raise ValueError("Reviewer actor must be at most 100 characters")


def event(conn, dataset, action, actor, notes, before=None, after=None, issue_id=None):
    conn.execute(
        audit.insert().values(
            dataset=dataset,
            action=action,
            actor=actor,
            notes=notes,
            before_json=before,
            after_json=after,
            issue_id=issue_id,
            occurred_at=now(),
        )
    )
    log.info(json.dumps({"event": action, "dataset": dataset, "actor": actor}))


def read_bundle(conn, name):
    state = conn.execute(select(datasets).where(datasets.c.name == name)).mappings().first()
    if not state:
        raise ValueError(f"Unknown staged dataset: {name}")
    data = {table: [] for table in TABLE_ORDER}
    refs = {table: [] for table in TABLE_ORDER}
    for row in conn.execute(
        select(records)
        .where(records.c.dataset == name, records.c.is_deleted.is_(False))
        .order_by(records.c.id)
    ).mappings():
        data[row["entity"]].append(row["payload"])
        refs[row["entity"]].append(row["record_ref"])
    return Bundle(name=name, data=data, **state["metadata_json"]), refs, state


def stage(engine, bundle: Bundle) -> int:
    bundle = Bundle.model_validate(bundle.model_dump())
    digest = fingerprint(bundle.model_dump(mode="json"))
    with engine.begin() as conn:
        lock(conn)
        existing = (
            conn.execute(select(datasets).where(datasets.c.name == bundle.name)).mappings().first()
        )
        if existing:
            if existing["content_hash"] != digest:
                raise ValueError(
                    "Dataset already exists with different content; use audited "
                    "corrections or a new dataset name"
                )
            return existing["version"]
        conn.execute(
            datasets.insert().values(
                name=bundle.name,
                version=1,
                content_hash=digest,
                metadata_json=bundle.model_dump(exclude={"name", "data"}, mode="json"),
                status="staged",
                updated_at=now(),
            )
        )
        values = [
            {
                "dataset": bundle.name,
                "entity": entity,
                "record_ref": f"{entity}:{i + 1}",
                "payload": row,
                "quarantined": False,
                "is_deleted": False,
                "updated_at": now(),
            }
            for entity, rows in bundle.data.items()
            for i, row in enumerate(rows)
        ]
        for offset in range(0, len(values), 1000):
            conn.execute(records.insert(), values[offset : offset + 1000])
        event(
            conn,
            bundle.name,
            "stage",
            "source-loader",
            "Synthetic source registered",
            after={"hash": digest, "version": 1, "rows": len(values)},
        )
    return 1


def validate_dataset(engine, name, config: QualityConfig | None = None, reference=None) -> Report:
    config = config or QualityConfig()
    started = now()
    with engine.begin() as conn:
        lock(conn)
        bundle, refs, state = read_bundle(conn, name)
        report = evaluate(bundle, config, reference, refs)
        timestamp = now()
        run_id = conn.execute(
            runs.insert().values(
                dataset=name,
                dataset_version=state["version"],
                content_hash=state["content_hash"],
                config_json=config.model_dump(mode="json"),
                report_json={},
                started_at=started,
                completed_at=timestamp,
                reference_at=report.reference_at,
                overall_score=report.overall_score,
                failed_records=report.failed_records,
            )
        ).inserted_primary_key[0]
        existing = {
            row["fingerprint"]: row
            for row in conn.execute(select(issues).where(issues.c.dataset == name)).mappings()
        }
        live_ids = set()
        failed = set()
        transitions = {"new": 0, "persistent": 0, "reopened": 0, "resolved": 0}
        for finding in report.findings:
            identity = fingerprint(
                [
                    name,
                    finding.rule_id,
                    finding.rule_version,
                    finding.entity,
                    finding.record_ref,
                    finding.field,
                ]
            )
            old = existing.get(identity)
            values = {"last_run_id": run_id, "last_seen_at": timestamp}
            if old:
                issue_id = old["id"]
                if old["status"] == "resolved":
                    values.update(status="open", resolved_at=None)
                    transitions["reopened"] += 1
                    event(
                        conn,
                        name,
                        "issue_reopened",
                        "validator",
                        "Finding recurred",
                        {"status": "resolved"},
                        {"status": "open"},
                        issue_id,
                    )
                else:
                    transitions["persistent"] += 1
                conn.execute(issues.update().where(issues.c.id == issue_id).values(**values))
            else:
                value = finding.model_dump(exclude={"dimension"})
                value.update(
                    dataset=name,
                    fingerprint=identity,
                    first_run_id=run_id,
                    last_run_id=run_id,
                    detected_at=timestamp,
                    last_seen_at=timestamp,
                    status="open",
                )
                issue_id = conn.execute(issues.insert().values(**value)).inserted_primary_key[0]
                transitions["new"] += 1
                event(
                    conn,
                    name,
                    "issue_opened",
                    "validator",
                    "New detected finding",
                    after={"rule_id": finding.rule_id},
                    issue_id=issue_id,
                )
            live_ids.add(issue_id)
            conn.execute(findings.insert().values(run_id=run_id, issue_id=issue_id))
            failed.add((finding.entity, finding.record_ref))
        for old in existing.values():
            if old["id"] not in live_ids and old["status"] != "resolved":
                conn.execute(
                    issues.update()
                    .where(issues.c.id == old["id"])
                    .values(
                        status="resolved",
                        resolved_at=timestamp,
                        resolution_notes="No longer detected on revalidation",
                    )
                )
                transitions["resolved"] += 1
                event(
                    conn,
                    name,
                    "issue_resolved",
                    "validator",
                    "No longer detected",
                    {"status": old["status"]},
                    {"status": "resolved"},
                    old["id"],
                )
        conn.execute(records.update().where(records.c.dataset == name).values(quarantined=False))
        for entity, ref in failed:
            conn.execute(
                records.update()
                .where(
                    records.c.dataset == name,
                    records.c.entity == entity,
                    records.c.record_ref == ref,
                )
                .values(quarantined=True)
            )
        conn.execute(
            datasets.update()
            .where(datasets.c.name == name)
            .values(status="quarantined" if report.findings else "validated", updated_at=timestamp)
        )
        report.run_id = run_id
        report.dataset_version = state["version"]
        report.transitions = transitions
        conn.execute(
            runs.update()
            .where(runs.c.id == run_id)
            .values(report_json=report.model_dump(mode="json"))
        )
        event(
            conn,
            name,
            "validation_complete",
            "validator",
            "Validation results persisted",
            after={
                "run_id": run_id,
                "version": state["version"],
                "issues": len(report.findings),
                "transitions": transitions,
            },
        )
    return report


def set_issue_status(engine, issue_id, status, actor, notes):
    review_identity(actor, notes)
    if status not in {"open", "acknowledged", "resolved", "false_positive"}:
        raise ValueError("Unknown issue status")
    with engine.begin() as conn:
        lock(conn)
        old = conn.execute(select(issues).where(issues.c.id == issue_id)).mappings().first()
        if not old:
            raise ValueError("Unknown issue")
        conn.execute(
            issues.update()
            .where(issues.c.id == issue_id)
            .values(
                status=status,
                resolution_notes=notes,
                resolved_at=now() if status == "resolved" else None,
            )
        )
        event(
            conn,
            old["dataset"],
            "issue_review",
            actor,
            notes,
            {"status": old["status"], "notes": old["resolution_notes"]},
            {"status": status, "notes": notes},
            issue_id,
        )


def correct_record(engine, name, entity, ref, patch, actor, notes, expected_version, delete=False):
    review_identity(actor, notes)
    if not isinstance(patch, dict) or (not patch and not delete):
        raise ValueError("Supply an explicit object patch or reviewed tombstone")
    with engine.begin() as conn:
        lock(conn)
        bundle, _, state = read_bundle(conn, name)
        if state["version"] != expected_version:
            raise ValueError("Dataset revision changed; reload and review before editing")
        if entity == "__metadata__":
            if delete:
                raise ValueError("Metadata cannot be deleted")
            old = state["metadata_json"]
            new = {**old, **patch}
            Bundle(name=name, data=bundle.data, **new)
            conn.execute(datasets.update().where(datasets.c.name == name).values(metadata_json=new))
        else:
            row = (
                conn.execute(
                    select(records).where(
                        records.c.dataset == name,
                        records.c.entity == entity,
                        records.c.record_ref == ref,
                        records.c.is_deleted.is_(False),
                    )
                )
                .mappings()
                .first()
            )
            if not row:
                raise ValueError("Unknown active staging record")
            old = {"payload": row["payload"], "is_deleted": False}
            new = {"payload": {**row["payload"], **patch}, "is_deleted": delete}
            conn.execute(
                records.update().where(records.c.id == row["id"]).values(**new, updated_at=now())
            )
        updated, _, _ = read_bundle(conn, name)
        version = expected_version + 1
        conn.execute(
            datasets.update()
            .where(datasets.c.name == name)
            .values(
                version=version,
                content_hash=fingerprint(updated.model_dump(mode="json")),
                status="staged",
                updated_at=now(),
            )
        )
        event(
            conn,
            name,
            "record_tombstone" if delete else "source_correction",
            actor,
            notes,
            {"entity": entity, "record_ref": ref, "value": old, "version": expected_version},
            {"entity": entity, "record_ref": ref, "value": new, "version": version},
        )
        return version


def latest_report(engine, name, run_id=None) -> Report:
    with engine.connect() as conn:
        query = select(runs.c.report_json).where(runs.c.dataset == name)
        if run_id is not None:
            query = query.where(runs.c.id == run_id)
        value = conn.scalar(query.order_by(runs.c.id.desc()).limit(1))
        if not value:
            raise ValueError("No stored validation run for this dataset")
        return Report.model_validate(value)


def approve(engine, name, expected_version, actor, notes) -> dict[str, int]:
    review_identity(actor, notes)
    with engine.begin() as conn:
        lock(conn)
        bundle, _, state = read_bundle(conn, name)
        if state["version"] != expected_version:
            raise ValueError("Dataset revision changed; revalidate the current revision")
        previous = (
            conn.execute(
                select(runs).where(runs.c.dataset == name).order_by(runs.c.id.desc()).limit(1)
            )
            .mappings()
            .first()
        )
        if (
            not previous
            or previous["dataset_version"] != expected_version
            or previous["content_hash"] != state["content_hash"]
        ):
            raise ValueError("Revalidation of this exact dataset revision is required")
        report = Report.model_validate(previous["report_json"])
        if report.findings:
            raise ValueError(
                "Uncorrected validation findings block approval, including reviewed false positives"
            )
        projected = {}
        for name_table in TABLE_ORDER:
            projected[name_table] = []
            for raw in bundle.data[name_table]:
                row = {column.name: raw.get(column.name) for column in tables[name_table].c}
                for field in row:
                    if field.endswith("_date"):
                        row[field] = parse_date(row[field])
                    if field in {"unit_price", "list_price", "unit_cost"}:
                        row[field] = Decimal(str(row[field]))
                projected[name_table].append(row)
        validate_foundation(projected)
        inserts = {}
        enrichments = []
        for name_table in TABLE_ORDER:
            table = tables[name_table]
            key = "batch_id" if name_table == "inventory" else "id"
            current = {row[key]: row for row in conn.execute(select(table)).mappings()}
            inserts[name_table] = []
            for row in projected[name_table]:
                old = current.get(row[key])
                if old is None:
                    inserts[name_table].append(row)
                    continue
                changed = {field: value for field, value in row.items() if old[field] != value}
                allowed = {"manufacturer", "contact_email", "is_sellable"}
                if any(field not in allowed or old[field] is not None for field in changed):
                    raise ValueError(
                        f"Production conflict in {name_table} record {row[key]}; reviewed "
                        f"source cannot overwrite existing business values"
                    )
                if changed:
                    enrichments.append(
                        {"table": name_table, "key": key, "id": row[key], "changes": changed}
                    )
        # Conflicts are checked before writes; failures also roll back the transaction.
        for name_table in TABLE_ORDER:
            for offset in range(0, len(inserts[name_table]), 1000):
                conn.execute(
                    tables[name_table].insert(), inserts[name_table][offset : offset + 1000]
                )
        for change in enrichments:
            table = tables[change["table"]]
            conn.execute(
                table.update()
                .where(table.c[change["key"]] == change["id"])
                .values(**change["changes"])
            )
        conn.execute(
            datasets.update()
            .where(datasets.c.name == name)
            .values(status="approved", updated_at=now())
        )
        event(
            conn,
            name,
            "approved_load",
            actor,
            notes,
            {"version": expected_version, "hash": state["content_hash"]},
            {
                "run_id": previous["id"],
                "inserted_ids": {
                    t: [r["batch_id" if t == "inventory" else "id"] for r in rows]
                    for t, rows in inserts.items()
                },
                "nullable_metadata_fill_v1": enrichments,
            },
        )
        return {
            table: conn.scalar(select(func.count()).select_from(tables[table]))
            for table in TABLE_ORDER
        }
