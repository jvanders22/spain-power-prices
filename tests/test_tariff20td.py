from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from spain_power import tariff20td as t

WEDNESDAY = dt.date(2026, 3, 4)


@pytest.mark.parametrize(
    ("hour", "expected"),
    [
        (0, "P3"),
        (7, "P3"),
        (8, "P2"),
        (9, "P2"),
        (10, "P1"),
        (13, "P1"),
        (14, "P2"),
        (17, "P2"),
        (18, "P1"),
        (21, "P1"),
        (22, "P2"),
        (23, "P2"),
    ],
)
def test_weekday_hour_boundaries(hour, expected):
    assert t.period(WEDNESDAY, hour) == expected


def test_hour_out_of_range():
    with pytest.raises(ValueError, match="hour"):
        t.period(WEDNESDAY, 24)


@pytest.mark.parametrize(
    "day",
    [
        dt.date(2026, 3, 7),  # Saturday
        dt.date(2026, 3, 8),  # Sunday
        dt.date(2026, 10, 12),  # Fiesta Nacional, a Monday
        dt.date(2026, 1, 6),  # Epiphany, a Tuesday
        dt.date(2025, 12, 25),  # a Thursday
        dt.date(2025, 5, 1),  # a Thursday
    ],
)
def test_weekends_and_fixed_holidays_are_valle_all_day(day):
    assert {t.period(day, h) for h in range(24)} == {"P3"}


def test_good_friday_is_a_normal_day():
    good_friday = dt.date(2026, 4, 3)
    assert not t.is_holiday(good_friday)
    assert t.period(good_friday, 11) == "P1"
    assert t.period(good_friday, 15) == "P2"


def test_tolls_and_charges_sum_per_period():
    assert t.tolls_and_charges() == {"P1": 97.553, "P2": 29.267, "P3": 3.292}


def _frame(start: str, end: str) -> pd.DataFrame:
    ts = pd.date_range(start, end, freq="h", tz="UTC").tz_convert("Europe/Madrid")
    return pd.DataFrame({"date": ts.strftime("%Y-%m-%d"), "hour": ts.hour, "price_es": 50.0})


def test_periods_matches_scalar_function(hourly):
    got = t.periods(hourly)
    want = [
        t.period(dt.date.fromisoformat(d), h) for d, h in zip(hourly["date"], hourly["hour"], strict=True)
    ]
    assert got.tolist() == want
    assert set(got) == {"P1", "P2", "P3"}


def test_periods_use_local_time_across_dst():
    # Friday 27 March 2026 is CET (UTC+1); Monday 30 March is CEST (UTC+2). 10:00 local is
    # punta on both, whatever the UTC hour.
    df = _frame("2026-03-27 00:00", "2026-03-30 23:00")
    p = t.periods(df)
    for day in ("2026-03-27", "2026-03-30"):
        on = df["date"] == day
        assert p[on & (df["hour"] == 9)].tolist() == ["P2"]
        assert p[on & (df["hour"] == 10)].tolist() == ["P1"]
    # The 25-hour Sunday in October: 02:00 happens twice and both are valle.
    autumn = _frame("2025-10-25 22:00", "2025-10-26 22:59")
    assert len(autumn) == 25 and (autumn["hour"] == 2).sum() == 2
    assert set(t.periods(autumn)) == {"P3"}


def test_summary_shares():
    df = _frame("2026-03-02 23:00", "2026-03-09 22:59")  # one local week, Tue-Mon
    df.loc[(df["date"] == "2026-03-04") & (df["hour"] == 12), "price_es"] = 0.0  # punta
    df.loc[(df["date"] == "2026-03-07") & (df["hour"] == 12), "price_es"] = -1.0  # Saturday
    s = t.summary(df)
    assert s["hours"].to_dict() == {"P1": 40, "P2": 40, "P3": 88}
    assert s["hours_share"].sum() == pytest.approx(1.0)
    assert s["low_hours"].to_dict() == {"P1": 1, "P2": 0, "P3": 1}
    assert s["low_share"].to_dict() == {"P1": 0.5, "P2": 0.0, "P3": 0.5}
    assert s.loc["P1", "tolls_and_charges"] == 97.553
