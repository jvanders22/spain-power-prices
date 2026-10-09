from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from spain_power import ree, transform


def test_build_hourly_derived_columns():
    ts = pd.date_range("2025-06-30 21:00", periods=3, freq="h", tz="UTC")
    prices = pd.DataFrame({"ts_utc": ts, "price_es": [50.0, -1.0, 10.0], "price_pt": [50.0, -1.0, 10.0]})
    gen = pd.DataFrame({"ts_utc": ts[:2], **{c: [0.0, 0.0] for c in ree.FIELDS.values()}})
    gen["demand"] = [20000.0, 25000.0]
    gen["wind"] = [4000.0, 5000.0]
    gen["solar_pv"] = [1000.0, 2000.0]
    gen["solar_thermal"] = [0.0, 500.0]
    gen["hydro"] = [-2000.0, 3000.0]  # first hour is net pumping

    df = transform.build_hourly(prices, gen)
    assert len(df) == 2  # inner join drops the price-only hour
    assert df["hydro_gen"].tolist() == [0.0, 3000.0]
    assert df["renewables"].tolist() == [5000.0, 10500.0]
    assert df["renewables_share"].tolist() == pytest.approx([0.25, 0.42])
    assert df["solar"].tolist() == [1000.0, 2500.0]
    # 21:00 UTC is 23:00 CEST on 30 June; 22:00 UTC is midnight on 1 July
    assert df["hour"].tolist() == [23, 0]
    assert df["date"].tolist() == ["2025-06-30", "2025-07-01"]
    assert df["month"].tolist() == ["2025-06", "2025-07"]


@pytest.fixture
def tiny() -> pd.DataFrame:
    """Four hours, hand-computable: baseload 55 / 4 = 13.75, solar capture (20*1 + 30*3) / 4 = 27.5."""
    return pd.DataFrame(
        {
            "month": ["2025-01"] * 4,
            "price_es": [10.0, 20.0, 30.0, -5.0],
            "solar": [0.0, 1.0, 3.0, 0.0],
            "wind": [1.0, 1.0, 1.0, 1.0],
            "demand": [10.0, 10.0, 10.0, 10.0],
            "renewables": [1.0, 2.0, 4.0, 1.0],
        }
    )


def test_capture_prices_exact(tiny):
    c = transform.capture_prices(tiny, freq="month")
    row = c.loc["2025-01"]
    assert row["baseload"] == pytest.approx(13.75)
    assert row["solar_capture"] == pytest.approx(27.5)
    assert row["wind_capture"] == pytest.approx(13.75)
    assert row["solar_capture_rate"] == pytest.approx(27.5 / 13.75)
    assert row["solar_share"] == pytest.approx(4 / 40)
    assert row["hours"] == 4


def test_kpis_exact(tiny):
    k = transform.kpis(tiny)
    assert k["avg_price"] == pytest.approx(13.75)
    assert k["zero_or_negative_hours"] == 1
    assert k["negative_hours"] == 1
    assert k["pct_zero_or_negative"] == pytest.approx(0.25)
    assert k["avg_renewables_share"] == pytest.approx(8 / 40)
    assert k["solar_capture"] == pytest.approx(27.5)
    assert k["solar_capture_rate"] == pytest.approx(2.0)
    assert k["hours"] == 4


def test_negative_hours_pivot(hourly):
    p = transform.negative_hours(hourly, threshold=60.0)
    assert p.shape == (3, 24)  # Dec, Jan, Feb x 24 hours
    assert list(p.index) == ["2024-12", "2025-01", "2025-02"]
    assert int(p.to_numpy().sum()) == int((hourly["price_es"] <= 60.0).sum())


def test_share_buckets(hourly):
    b = transform.share_buckets(hourly)
    assert list(b.columns) == ["mean", "median", "count"]
    assert b["count"].sum() == hourly["renewables_share"].notna().sum()
    assert all("%-" in lbl for lbl in b.index)


def test_filter_dates(hourly):
    f = transform.filter_dates(hourly, dt.date(2025, 1, 1), dt.date(2025, 1, 31))
    assert len(f) == 31 * 24
    assert f["month"].unique().tolist() == ["2025-01"]
