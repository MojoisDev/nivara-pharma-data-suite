from pathlib import Path

from streamlit.testing.v1 import AppTest

from pharma_suite.db import create_db
from pharma_suite.quality.demo import make_bundle
from pharma_suite.quality.store import stage, validate_dataset


def test_quality_page_reads_stored_runs_and_filters(tmp_path, monkeypatch, hand_data):
    url = f"sqlite:///{tmp_path}/quality.db"
    engine = create_db(url)
    clean = make_bundle(hand_data, "fixture-clean")
    bad = make_bundle(hand_data, "fixture-bad")
    bad.data["medicines"][0]["name"] = ""
    for bundle in (clean, bad):
        stage(engine, bundle)
        validate_dataset(engine, bundle.name)
        validate_dataset(engine, bundle.name)
    monkeypatch.setenv("DATABASE_URL", url)
    page = Path(__file__).resolve().parents[1] / "dashboard/pages/2_Data_Quality.py"
    app = AppTest.from_file(str(page)).run(timeout=30)
    assert not app.exception
    assert len(app.metric) >= 9
    app.sidebar.selectbox[0].set_value("fixture-clean").run()
    assert not app.exception
    assert app.metric[0].value == "100.00%"
    app.sidebar.selectbox[0].set_value("fixture-bad").run()
    assert not app.exception
    assert app.metric[1].value == "1 / 8"
    assert app.metric[3].value != "100.0000%"
    assert app.dataframe[0].value.open_issues.tolist() == [0, 1, 0]
    app.multiselect[0].set_value([]).run()
    assert not app.exception
