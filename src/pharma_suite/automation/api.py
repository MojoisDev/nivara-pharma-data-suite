"""Small trusted-local HTTP interface; all data and write endpoints require a bearer token."""

import hmac
import json
import os
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from pharma_suite.automation.alerts import acknowledge
from pharma_suite.automation.mail import deliver
from pharma_suite.automation.reporting import report_path
from pharma_suite.automation.scheduler import status
from pharma_suite.automation.schema import alerts, emails, executions, reports
from pharma_suite.automation.storage import safe_artifact
from pharma_suite.automation.workflow import enqueue


class WorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["daily", "weekly"] = "daily"
    actor: str = Field(min_length=1, max_length=100)
    notes: str = Field(min_length=1, max_length=2000)
    start: date | None = None
    end: date | None = None


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor: str = Field(min_length=1, max_length=100)
    notes: str = Field(min_length=1, max_length=2000)


def make_server(engine, config, host, port, token=None):
    token = token if token is not None else os.getenv("AUTOMATION_API_TOKEN", "")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Request headers/URLs may contain credentials; database events are the audit log.

        def respond(self, code, value, content_type="application/json", filename=None):
            payload = value if isinstance(value, bytes) else json.dumps(value, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(payload)

        def authorized(self):
            return bool(token) and hmac.compare_digest(
                self.headers.get("Authorization", "").encode("utf-8"),
                ("Bearer " + token).encode("utf-8"),
            )

        def do_GET(self):
            self.handle_request(False)

        def do_POST(self):
            self.handle_request(True)

        def handle_request(self, writing):
            path = urlsplit(self.path).path
            if not writing and path == "/health":
                try:
                    with engine.connect() as conn:
                        conn.execute(text("SELECT 1"))
                    self.respond(200, {"healthy": True})
                except SQLAlchemyError:
                    self.respond(503, {"healthy": False})
                return
            if not self.authorized():
                self.respond(
                    401, {"error": "Bearer authentication required; unset token denies access"}
                )
                return
            try:
                parts = path.strip("/").split("/")
                body = {}
                if writing:
                    size = int(self.headers.get("Content-Length", "0"))
                    if size < 0 or size > 16384:
                        raise ValueError("Request body exceeds limit")
                    self.connection.settimeout(10)
                    body = json.loads(self.rfile.read(size) or b"{}")
                if writing and path == "/workflows":
                    request = WorkflowRequest.model_validate(body)
                    key = self.headers.get("Idempotency-Key", "")
                    run_id = enqueue(
                        engine,
                        request.kind,
                        key,
                        request.actor,
                        request.notes,
                        config,
                        request.start,
                        request.end,
                    )
                    self.respond(202, {"execution_id": run_id})
                elif (
                    writing
                    and len(parts) == 3
                    and parts[0] == "alerts"
                    and parts[2] == "acknowledge"
                ):
                    request = ReviewRequest.model_validate(body)
                    acknowledge(engine, int(parts[1]), request.actor, request.notes)
                    self.respond(200, {"status": "acknowledged"})
                elif writing and len(parts) == 3 and parts[0] == "emails" and parts[2] == "deliver":
                    self.respond(200, {"status": deliver(engine, parts[1], config)})
                elif not writing and path == "/scheduler":
                    self.respond(200, status(engine))
                elif not writing and path in {"/executions", "/reports", "/alerts", "/emails"}:
                    table = {
                        "executions": executions,
                        "reports": reports,
                        "alerts": alerts,
                        "emails": emails,
                    }[parts[0]]
                    with engine.connect() as conn:
                        rows = [
                            dict(row)
                            for row in conn.execute(
                                select(table).order_by(table.c.id.desc()).limit(100)
                            ).mappings()
                        ]
                    self.respond(200, rows)
                elif not writing and len(parts) == 2 and parts[0] == "executions":
                    with engine.connect() as conn:
                        row = (
                            conn.execute(select(executions).where(executions.c.id == parts[1]))
                            .mappings()
                            .first()
                        )
                    if not row:
                        raise ValueError("Unknown execution")
                    self.respond(200, dict(row))
                elif (
                    not writing
                    and len(parts) == 3
                    and parts[0] == "reports"
                    and parts[2] == "download"
                ):
                    artifact = report_path(engine, parts[1], config)
                    self.respond(
                        200,
                        artifact.read_bytes(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        artifact.name,
                    )
                elif (
                    not writing
                    and len(parts) == 3
                    and parts[0] == "emails"
                    and parts[2] == "preview"
                ):
                    with engine.connect() as conn:
                        row = (
                            conn.execute(select(emails).where(emails.c.id == parts[1]))
                            .mappings()
                            .first()
                        )
                    if not row:
                        raise ValueError("Unknown email")
                    artifact = safe_artifact(config, row["filename"], row["sha256"])
                    self.respond(200, artifact.read_bytes(), "message/rfc822", artifact.name)
                else:
                    self.respond(404, {"error": "Unknown route"})
            except (ValueError, TypeError, OSError):
                self.respond(
                    400,
                    {
                        "error": "Invalid request, unknown record, unsafe artifact or rejected "
                        "configuration"
                    },
                )
            except SQLAlchemyError:
                self.respond(503, {"error": "Database unavailable; no partial request committed"})

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server
