import json
import threading
import urllib.error
import urllib.request

import pytest
from sqlalchemy import select

from pharma_suite.automation.api import make_server
from pharma_suite.automation.config import AutomationConfig
from pharma_suite.automation.schema import executions
from pharma_suite.db import create_db, ingest


def test_local_api_authentication_idempotency_and_bad_downloads(tmp_path, hand_data):
    engine = create_db(f"sqlite:///{tmp_path}/api.db")
    ingest(engine, hand_data)
    config = AutomationConfig(report_dir=str(tmp_path / "reports"))
    server = make_server(engine, config, "127.0.0.1", 0, "test-only-token")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = f"http://127.0.0.1:{server.server_port}"
    try:
        assert json.load(urllib.request.urlopen(root + "/health"))["healthy"]
        with pytest.raises(urllib.error.HTTPError) as unauthorized:
            urllib.request.urlopen(root + "/executions")
        assert unauthorized.value.code == 401
        with pytest.raises(urllib.error.HTTPError) as malformed:
            urllib.request.urlopen(
                urllib.request.Request(
                    root + "/executions", headers={"Authorization": "Bearer café"}
                )
            )
        assert malformed.value.code == 401
        body = json.dumps(
            {"kind": "daily", "actor": "reviewer", "notes": "Synthetic API probe"}
        ).encode()
        headers = {
            "Authorization": "Bearer test-only-token",
            "Content-Type": "application/json",
            "Idempotency-Key": "api-1",
        }
        response = json.load(
            urllib.request.urlopen(urllib.request.Request(root + "/workflows", body, headers))
        )
        repeated = json.load(
            urllib.request.urlopen(urllib.request.Request(root + "/workflows", body, headers))
        )
        assert response["execution_id"] == repeated["execution_id"]
        with engine.connect() as conn:
            assert conn.execute(select(executions.c.status)).scalar_one() == "queued"
        with pytest.raises(urllib.error.HTTPError) as invalid:
            urllib.request.urlopen(
                urllib.request.Request(root + "/reports/../../etc/passwd/download", headers=headers)
            )
        assert invalid.value.code in {400, 404}
        with pytest.raises(urllib.error.HTTPError) as bad_input:
            urllib.request.urlopen(
                urllib.request.Request(root + "/workflows", b'{"kind":"unknown"}', headers)
            )
        assert bad_input.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
