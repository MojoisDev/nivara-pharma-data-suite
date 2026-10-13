from pathlib import Path

from sqlalchemy import func, select
from streamlit.testing.v1 import AppTest

from pharma_suite.automation.config import AutomationConfig
from pharma_suite.automation.schema import executions
from pharma_suite.automation.workflow import enqueue, execute_inline
from pharma_suite.db import create_db, ingest


def test_monitoring_reads_history_and_requires_confirmation(tmp_path, hand_data, monkeypatch):
    url = f"sqlite:///{tmp_path}/dashboard.db"
    engine = create_db(url)
    ingest(engine, hand_data)
    config = AutomationConfig(report_dir=str(tmp_path / "reports"))
    path = tmp_path / "config.json"
    path.write_text(config.model_dump_json())
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("AUTOMATION_CONFIG", str(path))
    run_id = enqueue(engine, "daily", "dashboard-1", "reviewer", "UI fixture", config)
    execute_inline(engine, run_id, config)
    page = Path(__file__).resolve().parents[1] / "dashboard/pages/3_Automation.py"
    app = AppTest.from_file(str(page)).run(timeout=30)
    assert not app.exception
    assert app.metric[0].value == "1"
    button = next(b for b in app.button if b.label == "Queue confirmed workflow")
    button.click().run()
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(executions)) == 1
    app.checkbox[0].set_value(True)
    next(t for t in app.text_input if t.label == "Workflow reviewer").set_value("test-reviewer")
    next(t for t in app.text_area if t.label == "Workflow purpose / evidence").set_value(
        "Confirmed synthetic report"
    )
    next(b for b in app.button if b.label == "Queue confirmed workflow").click().run()
    assert not app.exception
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(executions)) == 2
        assert (
            conn.scalar(
                select(func.count()).select_from(executions).where(executions.c.status == "queued")
            )
            == 1
        )
