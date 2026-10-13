from pathlib import Path

from streamlit.testing.v1 import AppTest

from pharma_suite.db import create_db, ingest
from pharma_suite.generate import generate


def test_dashboard_filters_and_empty_selection(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path}/dashboard.db"
    ingest(create_db(url), generate())
    monkeypatch.setenv("DATABASE_URL", url)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "dashboard/app.py"))
    app.run(timeout=30)
    assert not app.exception
    assert len(app.metric) == 7
    app.multiselect[0].set_value([]).run()
    assert not app.exception
    assert app.metric[0].value == "₹0"
    assert app.metric[2].value == "₹0"
    assert app.metric[3].value == "—"
    app.multiselect[0].set_value(["North"]).run()
    assert not app.exception
    assert app.metric[0].value != "₹0"
