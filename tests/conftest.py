import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest


@pytest.fixture
def hand_data():
    data = json.loads((Path(__file__).parent / "fixtures" / "hand_verified.json").read_text())
    for rows in data.values():
        for row in rows:
            for key, value in row.items():
                if key.endswith("_date"):
                    row[key] = date.fromisoformat(value)
                if key in {"unit_cost", "list_price", "unit_price"}:
                    row[key] = Decimal(value)
    return data


@pytest.fixture(autouse=True)
def never_send_real_mail(monkeypatch):
    monkeypatch.setenv("MAIL_MODE", "preview")
    monkeypatch.setenv("SMTP_ALLOW_EXTERNAL", "false")

    def prohibited(*args, **kwargs):
        raise AssertionError("Tests must explicitly mock SMTP; real delivery is prohibited")

    monkeypatch.setattr("smtplib.SMTP", prohibited)
    monkeypatch.setattr("smtplib.SMTP_SSL", prohibited)
