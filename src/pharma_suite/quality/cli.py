"""Run with `pharma dq ...` or `python -m pharma_suite.quality.cli ...`."""

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from pharma_suite.db import create_db
from pharma_suite.quality.demo import demo, expected_manifest
from pharma_suite.quality.models import Bundle, QualityConfig
from pharma_suite.quality.schema import datasets
from pharma_suite.quality.store import (
    approve,
    correct_record,
    latest_report,
    set_issue_status,
    stage,
    validate_dataset,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    generate = sub.add_parser("generate")
    generate.add_argument("--output", type=Path, default=Path("data/quality"))
    staging = sub.add_parser("stage")
    staging.add_argument("--file", type=Path, required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--dataset", default="demo-clean")
    validate.add_argument("--config", type=Path)
    validate.add_argument(
        "--as-of", help="Timezone-aware ISO clock; demo default is historical replay"
    )
    report = sub.add_parser("report")
    report.add_argument("--dataset", default="demo-clean")
    report.add_argument("--run-id", type=int)
    manifest = sub.add_parser("verify-manifest")
    manifest.add_argument("--dataset", default="demo-corrupted")
    manifest.add_argument("--file", type=Path, default=Path("data/quality/fault_manifest.json"))
    edit = sub.add_parser("correct")
    edit.add_argument("--dataset", required=True)
    edit.add_argument("--entity", required=True)
    edit.add_argument("--record", required=True)
    changes = edit.add_mutually_exclusive_group(required=True)
    changes.add_argument("--patch", help="Explicit JSON object; no implicit normalization")
    changes.add_argument(
        "--delete", action="store_true", help="Reviewed tombstone; original remains in audit"
    )
    approval = sub.add_parser("approve")
    approval.add_argument("--dataset", required=True)
    review = sub.add_parser("issue")
    review.add_argument("--id", type=int, required=True)
    review.add_argument(
        "--status", choices=["open", "acknowledged", "resolved", "false_positive"], required=True
    )
    for command in (edit, approval, review):
        command.add_argument("--actor", required=True)
        command.add_argument("--notes", required=True)
    for command in (edit, approval):
        command.add_argument("--expected-version", type=int, required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        if args.action == "generate":
            args.output.mkdir(parents=True, exist_ok=True)
            for name in ("demo-clean", "demo-corrupted"):
                (args.output / f"{name}.json").write_text(
                    demo(name).model_dump_json(indent=2) + "\n"
                )
            (args.output / "fault_manifest.json").write_text(
                json.dumps(expected_manifest(), indent=2) + "\n"
            )
            print(json.dumps({"event": "quality_demo_generated", "path": str(args.output)}))
            return
        engine = create_db()
        if args.action == "stage":
            bundle = Bundle.model_validate_json(args.file.read_text())
            print(json.dumps({"dataset": bundle.name, "version": stage(engine, bundle)}))
        elif args.action == "validate":
            with engine.connect() as conn:
                present = conn.scalar(
                    select(func.count())
                    .select_from(datasets)
                    .where(datasets.c.name == args.dataset)
                )
            if not present and args.dataset in {"demo-clean", "demo-corrupted"}:
                stage(engine, demo(args.dataset))
            config = (
                QualityConfig.model_validate_json(args.config.read_text())
                if args.config
                else QualityConfig()
            )
            reference = datetime.fromisoformat(args.as_of) if args.as_of else None
            result = validate_dataset(engine, args.dataset, config, reference)
            print(result.model_dump_json(indent=2, exclude={"findings", "rules"}))
        elif args.action == "report":
            print(latest_report(engine, args.dataset, args.run_id).model_dump_json(indent=2))
        elif args.action == "correct":
            version = correct_record(
                engine,
                args.dataset,
                args.entity,
                args.record,
                json.loads(args.patch) if args.patch else {},
                args.actor,
                args.notes,
                args.expected_version,
                args.delete,
            )
            print(
                json.dumps(
                    {"dataset": args.dataset, "version": version, "requires_revalidation": True}
                )
            )
        elif args.action == "approve":
            print(
                json.dumps(
                    approve(engine, args.dataset, args.expected_version, args.actor, args.notes),
                    indent=2,
                )
            )
        elif args.action == "issue":
            set_issue_status(engine, args.id, args.status, args.actor, args.notes)
            print(json.dumps({"issue_id": args.id, "status": args.status}))
        elif args.action == "verify-manifest":
            value = json.loads(args.file.read_text())
            actual = latest_report(engine, args.dataset).findings
            expected = {
                (f["rule_id"], f["rule_version"], f["entity"], f["record_ref"], f["field"])
                for f in value["findings"]
            }
            observed = {
                (f.rule_id, f.rule_version, f.entity, f.record_ref, f.field) for f in actual
            }
            print(
                json.dumps(
                    {
                        "expected": len(expected),
                        "detected": len(observed),
                        "missing": sorted(expected - observed),
                        "unexpected": sorted(observed - expected),
                    },
                    indent=2,
                )
            )
            if expected != observed:
                raise SystemExit(1)
    except (ValueError, ValidationError, SQLAlchemyError, OSError) as exc:
        message = (
            str(exc)
            if not isinstance(exc, SQLAlchemyError)
            else "Database operation failed; rolled back. Check connectivity and schema."
        )
        logging.error(
            json.dumps(
                {
                    "event": "quality_command_failed",
                    "error_type": type(exc).__name__,
                    "message": message,
                }
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
