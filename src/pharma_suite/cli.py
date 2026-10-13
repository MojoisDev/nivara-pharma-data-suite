"""Local commands: generate, init, ingest, verify."""

import argparse
import csv
import json
import logging
import sys
from pathlib import Path

from pharma_suite.db import create_db, ingest
from pharma_suite.generate import SEED, generate


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "auto":
        from pharma_suite.automation.cli import main as automation_main

        automation_main(sys.argv[2:])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "dq":
        from pharma_suite.quality.cli import main as quality_main

        quality_main(sys.argv[2:])
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["generate", "init", "ingest", "verify", "seed"])
    parser.add_argument("--output", type=Path, default=Path("data/synthetic"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.command == "generate":
        data = generate()
        args.output.mkdir(parents=True, exist_ok=True)
        for name, rows in data.items():
            with (args.output / f"{name}.csv").open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        (args.output / "manifest.json").write_text(
            json.dumps(
                {
                    "synthetic": True,
                    "seed": SEED,
                    "snapshot": "2025-12-31",
                    "rows": {name: len(rows) for name, rows in data.items()},
                },
                indent=2,
            )
            + "\n"
        )
        print(f"Synthetic CSVs written to {args.output}")
        return
    engine = create_db()
    if args.command == "seed":
        from sqlalchemy import func, select

        from pharma_suite.schema import tables

        with engine.connect() as conn:
            counts = {
                name: conn.scalar(select(func.count()).select_from(table))
                for name, table in tables.items()
            }
        if not any(counts.values()):
            print(json.dumps(ingest(engine, generate()), indent=2))
        elif not all(counts.values()):
            raise ValueError("Partial foundation detected; seed will not overwrite existing rows")
        else:
            print("Existing Phase 1 data preserved")
    elif args.command == "ingest":
        print(json.dumps(ingest(engine, generate()), indent=2))
    elif args.command == "verify":
        from sqlalchemy import func, select

        from pharma_suite.schema import tables

        with engine.connect() as conn:
            print(
                json.dumps(
                    {
                        name: conn.scalar(select(func.count()).select_from(table))
                        for name, table in tables.items()
                    },
                    indent=2,
                )
            )
    else:
        print("Foundation schema initialized")


if __name__ == "__main__":
    main()
