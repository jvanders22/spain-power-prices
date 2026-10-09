from __future__ import annotations

import pandas as pd
import pytest

from spain_power import omie


@pytest.fixture
def jan(fixture_text) -> pd.DataFrame:
    return omie.parse_marginalpdbc(fixture_text("marginalpdbc_20250101.1"))


@pytest.fixture
def dst(fixture_text) -> pd.DataFrame:
    return omie.parse_marginalpdbc(fixture_text("marginalpdbc_20251026.1"))


def test_parse_hourly_file(jan):
    assert len(jan) == 24
    assert list(jan.columns) == ["ts", "price_es", "price_pt", "mtu_min"]
    assert set(jan["mtu_min"]) == {60}
    assert jan["price_es"].iloc[0] == pytest.approx(134.49)
    assert str(jan["ts"].dt.tz) == "Europe/Madrid"
    assert jan["ts"].iloc[0] == pd.Timestamp("2025-01-01 00:00", tz="Europe/Madrid")
    # file columns are price_PT then price_ES
    row = jan[jan["ts"].dt.hour == 10].iloc[0]
    assert (row["price_pt"], row["price_es"]) == (pytest.approx(50.01), pytest.approx(35.0))


def test_parse_15min_dst_file(dst):
    assert len(dst) == 100
    assert set(dst["mtu_min"]) == {15}
    assert dst["price_es"].iloc[0] == pytest.approx(105.19)
    assert dst["ts"].dt.tz is not None
    utc = dst["ts"].dt.tz_convert("UTC")
    assert utc.is_unique and utc.is_monotonic_increasing
    assert utc.iloc[0] == pd.Timestamp("2025-10-25 22:00", tz="UTC")
    assert utc.iloc[-1] == pd.Timestamp("2025-10-26 22:45", tz="UTC")


def test_parse_rejects_empty():
    with pytest.raises(ValueError):
        omie.parse_marginalpdbc("MARGINALPDBC;\n*\n")


def test_to_hourly_regular_day(jan):
    h = omie.to_hourly(jan)
    assert len(h) == 24
    assert list(h.columns) == ["ts_utc", "price_es", "price_pt"]
    assert h["price_es"].tolist() == pytest.approx(jan["price_es"].tolist())


def test_to_hourly_dst_day(dst):
    h = omie.to_hourly(dst)
    assert len(h) == 25
    assert h["ts_utc"].is_unique
    first = h.set_index("ts_utc").loc[pd.Timestamp("2025-10-25 22:00", tz="UTC"), "price_es"]
    assert first == pytest.approx(dst["price_es"].iloc[:4].mean())
    assert first == pytest.approx((105.19 + 96.69 + 94.4 + 93.68) / 4)
