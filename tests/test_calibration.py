import datetime as dt
from pathlib import Path

import pandas as pd
import pytest

from spain_power import omie, ree, transform

FIX = Path(__file__).parent / "fixtures"


def test_parse_redata_daily_maps_techs():
    long = ree.parse_redata_daily((FIX / "redata_structure_peninsular.json").read_text())
    assert set(long["column"]) == {"wind", "solar_pv", "solar_thermal", "hydro_gen"}
    assert long["date"].nunique() == 3
    assert (long["mwh"] > 0).all()


def _hourly(day: str, solar: float, demand: float) -> pd.DataFrame:
    ts = pd.date_range(f"{day} 00:00", periods=24, freq="h", tz="Europe/Madrid").tz_convert("UTC")
    prices = pd.DataFrame({"ts_utc": ts, "price_es": 50.0, "price_pt": 50.0})
    gen = pd.DataFrame(
        {
            "ts_utc": ts,
            "demand": demand,
            "wind": 0.0,
            "solar_pv": solar,
            "solar_thermal": 0.0,
            "hydro": 0.0,
            "nuclear": 0.0,
            "combined_cycle": 0.0,
            "coal": 0.0,
            "cogeneration_other": 0.0,
        }
    )
    return prices, gen


def test_calibrate_daily_rescales_to_official_totals():
    prices, gen = _hourly("2026-01-15", solar=100.0, demand=1000.0)
    daily = pd.DataFrame(
        {
            "date": ["2026-01-15"],
            "solar_pv": [1800.0],
            "demand": [24000.0],
            "wind": [0.0],
            "solar_thermal": [0.0],
            "hydro_gen": [0.0],
        }
    )
    df = transform.build_hourly(prices, gen, daily)
    assert df["solar_pv"].sum() == pytest.approx(1800.0)
    assert df["solar_pv_rt"].sum() == pytest.approx(2400.0)
    assert df["demand"].sum() == pytest.approx(24000.0)
    assert df["solar_share"].iloc[0] == pytest.approx(0.075)
    assert df["calibrated"].all()


def test_calibrate_daily_missing_day_keeps_realtime_level():
    prices, gen = _hourly("2026-01-15", solar=100.0, demand=1000.0)
    daily = pd.DataFrame({"date": ["2026-01-14"], "solar_pv": [1.0], "demand": [1.0]})
    df = transform.build_hourly(prices, gen, daily)
    assert df["solar_pv"].sum() == pytest.approx(2400.0)
    assert not df["calibrated"].any()


def test_omie_fetch_day_falls_back_to_next_version(monkeypatch):
    text = (FIX / "marginalpdbc_20250101.1").read_text()
    seen = []

    def fake(url, **kw):
        seen.append(url[-1])
        if url.endswith(".3"):
            return text
        raise RuntimeError("HTTP 404")

    monkeypatch.setattr(omie, "get_text", fake)
    df = omie.fetch_day(dt.date(2025, 1, 1))
    assert seen == ["1", "2", "3"]
    assert len(df) == 24


def _full_daily(**kw):
    base = {
        "date": ["2026-01-15"],
        "solar_pv": [1800.0],
        "demand": [24000.0],
        "wind": [0.0],
        "solar_thermal": [0.0],
        "hydro_gen": [0.0],
    }
    base.update(kw)
    return pd.DataFrame(base)


def test_calibration_skips_partial_days():
    prices, gen = _hourly("2026-01-15", solar=100.0, demand=1000.0)
    df = transform.build_hourly(prices, gen.iloc[:20], _full_daily())
    assert not df["calibrated"].any()
    assert df["solar_pv"].sum() == pytest.approx(2000.0)


def test_calibration_missing_price_hour_does_not_distort_scaling():
    prices, gen = _hourly("2026-01-15", solar=100.0, demand=1000.0)
    df = transform.build_hourly(prices.iloc[1:], gen, _full_daily())
    assert df["calibrated"].all()
    assert df["solar_pv"].iloc[0] == pytest.approx(75.0)  # 1800/2400 * 100, not 1800/2300


def test_calibration_requires_every_series():
    prices, gen = _hourly("2026-01-15", solar=100.0, demand=1000.0)
    daily = _full_daily().drop(columns=["wind"])
    df = transform.build_hourly(prices, gen, daily)
    assert not df["calibrated"].any()
    assert df["solar_pv"].sum() == pytest.approx(2400.0)


def test_dst_expected_hours():
    assert transform.expected_hours("2025-03-30") == 23
    assert transform.expected_hours("2025-10-26") == 25
    assert transform.expected_hours("2025-06-01") == 24


def test_upsert_daily_keeps_history_and_old_values():
    from spain_power import cache

    old = pd.DataFrame({"date": ["2025-01-01", "2025-01-02"], "wind": [1.0, 2.0], "demand": [10.0, 20.0]})
    new = pd.DataFrame({"date": ["2025-01-02", "2025-01-03"], "wind": [5.0, 6.0], "demand": [None, 30.0]})
    m = cache.upsert_daily(old, new).set_index("date")
    assert list(m.index) == ["2025-01-01", "2025-01-02", "2025-01-03"]
    assert m.loc["2025-01-02", "wind"] == 5.0
    assert m.loc["2025-01-02", "demand"] == 20.0  # null in the new response keeps the cached value


def test_ree_missing_required_field_raises():
    import json

    payload = {"valoresHorariosGeneracion": [{"ts": "2025-01-01 00:00", "dem": 1, "eol": 1, "hid": 1}]}
    with pytest.raises(ValueError, match="solFot"):
        ree.parse_demanda(f"null({json.dumps(payload)});", dt.date(2025, 1, 1))


def test_headline_short_range_does_not_crash():
    from spain_power import findings

    prices, gen = _hourly("2026-01-15", solar=100.0, demand=1000.0)
    df = transform.build_hourly(prices, gen, None)
    h = findings.headline(df)
    assert h["worst_capture_month"][0] is None
