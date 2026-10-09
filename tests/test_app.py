"""Smoke-test the Streamlit script headlessly against a synthetic hourly parquet."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import synthetic_inputs

from spain_power.transform import build_hourly

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
APP = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"


@pytest.fixture
def app(tmp_path, monkeypatch):
    path = tmp_path / "hourly.parquet"
    build_hourly(*synthetic_inputs()).to_parquet(path, index=False)
    monkeypatch.setenv("SPAIN_POWER_HOURLY", str(path))
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.run()
    return at


def test_app_renders(app):
    assert not app.exception
    assert app.title[0].value == "Spanish power prices vs renewables"
    assert "OMIE" in app.caption[0].value and "01 Dec 2024" in app.caption[0].value
    assert len(app.metric) == 5
    assert [t.label for t in app.tabs] == [
        "Price vs renewables",
        "Zero/negative hours",
        "Solar cannibalisation",
        "Data",
    ]
    assert "Not affiliated" in app.caption[-1].value


def test_app_threshold_changes_kpi(app):
    before = app.metric[1].value
    app.number_input[0].set_value(60.0).run()
    assert not app.exception
    assert app.metric[1].label == "Hours ≤ 60 EUR/MWh"
    assert app.metric[1].value != before


def test_app_missing_data(tmp_path, monkeypatch):
    monkeypatch.setenv("SPAIN_POWER_HOURLY", str(tmp_path / "nope.parquet"))
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.run()
    assert not at.exception
    assert "No data" in at.error[0].value
