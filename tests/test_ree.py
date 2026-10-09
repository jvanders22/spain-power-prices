from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from spain_power import ree

DAY = dt.date(2025, 10, 26)


@pytest.fixture
def demanda(fixture_text) -> pd.DataFrame:
    return ree.parse_demanda(fixture_text("ree_demanda_20251026.jsonp"), DAY)


def test_parse_demanda_columns_and_day(demanda):
    assert list(demanda.columns) == ["ts", *ree.FIELDS.values()]
    assert demanda["ts"].notna().all()
    assert str(demanda["ts"].dt.tz) == "Europe/Madrid"
    # previous-evening rows in the payload are dropped; 25 local hours x 12 five-minute rows remain
    assert (demanda["ts"].dt.date == DAY).all()
    assert len(demanda) == 25 * 12


def test_parse_demanda_keeps_2a_and_2b(fixture_text, demanda):
    utc = demanda["ts"].dt.tz_convert("UTC")
    assert utc.is_unique
    two = utc[demanda["ts"].dt.hour == 2]
    assert len(two) == 24  # 2A (CEST) and 2B (CET), 12 rows each
    assert pd.Timestamp("2025-10-26 00:00", tz="UTC") in set(two)  # 2A:00
    assert pd.Timestamp("2025-10-26 01:00", tz="UTC") in set(two)  # 2B:00
    text = fixture_text("ree_demanda_20251026.jsonp")
    assert " 2A:" in text and " 2B:" in text


def test_to_hourly_25_hours(demanda):
    h = ree.to_hourly(demanda)
    assert len(h) == 25
    assert h["ts_utc"].nunique() == 25
    assert h["ts_utc"].notna().all()
    assert h["ts_utc"].iloc[0] == pd.Timestamp("2025-10-25 22:00", tz="UTC")
    assert h["ts_utc"].iloc[-1] == pd.Timestamp("2025-10-26 22:00", tz="UTC")
    assert (h["demand"] > 0).all()


def test_parse_redata_renewables(fixture_text):
    df = ree.parse_redata_renewables(fixture_text("redata_renewables.json"))
    assert list(df.columns) == ["date", "renewable", "non_renewable"]
    assert len(df) == 3
    assert df["date"].iloc[0] == dt.date(2025, 1, 1)
    assert df["renewable"].iloc[0] == pytest.approx(249586.0575)
    assert df["non_renewable"].iloc[-1] == pytest.approx(330674.1605)


def test_parse_redata_errors():
    with pytest.raises(RuntimeError, match="bad range"):
        ree.parse_redata_renewables('{"errors": [{"detail": "bad range"}]}')
