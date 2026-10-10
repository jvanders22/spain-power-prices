"""Open-Meteo previous-runs client: parser, cache and aggregation, on a recorded response."""

from __future__ import annotations

import datetime as dt
import json

import pandas as pd
import pytest

from spain_power import weather

FIXTURE = "open_meteo_previous_day3.json"  # 1-2 Mar 2025, all six points
START, END = dt.date(2025, 3, 1), dt.date(2025, 3, 2)


def test_parse_fixture(fixture_text):
    wx = weather.parse(fixture_text(FIXTURE))
    assert len(wx) == 48 and wx["ts_utc"].is_monotonic_increasing
    assert str(wx["ts_utc"].dt.tz) == "UTC"
    assert wx["ts_utc"].iloc[0] == pd.Timestamp("2025-03-01 00:00", tz="UTC")
    assert set(wx.columns) == {"ts_utc"} | {f"{v}_{p}" for v in weather.VARIABLES for p in weather.POINTS}
    noon = wx[wx["ts_utc"] == pd.Timestamp("2025-03-01 12:00", tz="UTC")].iloc[0]
    assert noon["rad_seville"] == 559.0 and noon["wind_seville"] == 1.06 and noon["temp_seville"] == 16.5
    assert wx.notna().all().all()
    assert (wx.filter(like="rad_") >= 0).all().all()


def test_request_asks_for_previous_day3_fields_only(monkeypatch):
    seen = {}

    def fake(url, *, params, timeout):
        seen.update(params, url=url)
        return "{}"

    monkeypatch.setattr(weather, "get_text", fake)
    weather.fetch_chunk(START, END)
    assert seen["url"].startswith("https://previous-runs-api.open-meteo.com/")
    assert seen["hourly"].split(",") == weather.fields()
    assert all(f.endswith("_previous_day3") for f in seen["hourly"].split(","))
    assert (
        seen["timezone"] == "GMT" and seen["start_date"] == "2025-03-01" and seen["end_date"] == "2025-03-02"
    )
    assert len(seen["latitude"].split(",")) == len(weather.POINTS) <= 6


def test_parse_rejects_other_fields_points_and_timezones(fixture_text):
    raw = json.loads(fixture_text(FIXTURE))

    def altered(change) -> str:
        data = json.loads(json.dumps(raw))
        change(data)
        return json.dumps(data)

    for leak in ["shortwave_radiation", "shortwave_radiation_previous_day2", "temperature_2m_previous_day1"]:
        text = altered(lambda d, leak=leak: d[0]["hourly"].update({leak: [0.0] * 48}))
        with pytest.raises(ValueError, match="only previous_day3 fields are allowed"):
            weather.parse(text)
    with pytest.raises(ValueError, match="expected 6 points, got 5"):
        weather.parse(altered(lambda d: d.pop()))
    with pytest.raises(ValueError, match="seville: response is for"):
        weather.parse(altered(lambda d: d[0].update(latitude=40.4)))
    with pytest.raises(ValueError, match="not in UTC"):
        weather.parse(altered(lambda d: d[2].update(utc_offset_seconds=3600)))


def test_load_reads_the_cache_and_fetches_only_what_is_missing(fixture_text, tmp_path, monkeypatch):
    with pytest.raises(FileNotFoundError, match="no cached weather for 2025-03-01 to 2025-03-02"):
        weather.load(START, END, cache=tmp_path, fetch=False)

    calls = []

    def fake(start, end):
        calls.append((start, end))
        return fixture_text(FIXTURE)

    monkeypatch.setattr(weather, "fetch_chunk", fake)
    wx = weather.load(START, END, cache=tmp_path)
    assert calls == [(START, END)] and len(wx) == 48
    assert (tmp_path / "previous_day3_2025Q1.json").read_text(encoding="utf-8") == fixture_text(FIXTURE)

    # Cached now: no request, same frame, and a sub-range is cut from it.
    pd.testing.assert_frame_equal(weather.load(START, END, cache=tmp_path, fetch=False), wx)
    assert len(weather.load(END, END, cache=tmp_path, fetch=False)) == 24
    assert calls == [(START, END)]
    # A later day is not covered by the cached file.
    with pytest.raises(FileNotFoundError):
        weather.load(START, dt.date(2025, 3, 3), cache=tmp_path, fetch=False)


def test_quarters():
    q = weather.quarters(dt.date(2024, 9, 30), dt.date(2025, 1, 2))
    assert [label for label, _, _ in q] == ["2024Q3", "2024Q4", "2025Q1"]
    assert q[1][1:] == (dt.date(2024, 10, 1), dt.date(2024, 12, 31))


def test_aggregate_by_hand():
    cols = {f"{v}_{p}": [0.0] for v in weather.VARIABLES for p in weather.POINTS}
    cols.update(
        rad_seville=[100.0], rad_badajoz=[200.0], rad_ciudad_real=[300.0], rad_zaragoza=[400.0],
        rad_burgos=[9999.0],  # not a solar point
        wind_ciudad_real=[2.0], wind_zaragoza=[4.0], wind_burgos=[6.0], wind_a_coruna=[20.0],
        wind_seville=[99.0],  # not a wind point
        temp_seville=[12.0],
    )  # fmt: skip
    wx = pd.DataFrame({"ts_utc": pd.to_datetime(["2025-03-01 12:00"], utc=True), **cols})
    out = weather.aggregate(wx).iloc[0]
    assert out["wx_rad"] == 250.0
    assert out["wx_wind"] == 8.0
    assert out["wx_wind3"] == pytest.approx((2**3 + 4**3 + 6**3 + 12**3) / 4)  # 20 m/s capped at 12
    assert out["wx_temp"] == 2.0
    assert list(weather.aggregate(wx).columns) == ["ts_utc", "wx_rad", "wx_wind", "wx_wind3", "wx_temp"]
