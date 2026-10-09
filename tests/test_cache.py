from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from spain_power import cache, omie, ree

START, END = dt.date(2025, 1, 1), dt.date(2025, 1, 4)


@pytest.fixture
def fake_sources(monkeypatch, fixture_text):
    """Replace the network fetchers: OMIE replays the 1 Jan fixture for any day, REE is synthetic."""
    template = fixture_text("marginalpdbc_20250101.1")
    calls: dict[str, list[dt.date]] = {"omie": [], "ree": []}

    def fetch_omie(day: dt.date) -> pd.DataFrame:
        calls["omie"].append(day)
        if day == dt.date(2025, 1, 3):
            raise RuntimeError("HTTP 404")
        return omie.parse_marginalpdbc(template.replace("2025;01;01", f"{day:%Y;%m;%d}"))

    def fetch_ree(day: dt.date) -> pd.DataFrame:
        calls["ree"].append(day)
        ts = pd.date_range(pd.Timestamp(day), periods=24 * 12, freq="5min", tz=ree.TZ)
        df = pd.DataFrame({"ts": ts, **{c: 1000.0 for c in ree.FIELDS.values()}})
        df["demand"] = 25000.0
        df["solar_pv"] = np.where(ts.hour.isin(range(10, 17)), 8000.0, 0.0)
        return df

    monkeypatch.setitem(cache.SOURCES, "omie", (fetch_omie, omie.to_hourly))
    monkeypatch.setitem(cache.SOURCES, "ree", (fetch_ree, ree.to_hourly))
    return calls


def test_fetch_range_and_rebuild(tmp_path, fake_sources):
    raw = tmp_path / "raw"
    failed = cache.fetch_range("omie", START, END, raw=raw, workers=2)
    assert failed == [dt.date(2025, 1, 3)]
    assert sorted(p.name for p in (raw / "omie").glob("*.parquet")) == [
        "20250101.parquet",
        "20250102.parquet",
        "20250104.parquet",
    ]
    assert cache.fetch_range("ree", START, END, raw=raw, workers=2) == []

    # second run: cached days are skipped, the failed day is retried, the last 2 days are re-fetched
    fake_sources["omie"].clear()
    cache.fetch_range("omie", START, END, raw=raw, force_recent_days=2)
    assert sorted(fake_sources["omie"]) == [dt.date(2025, 1, 3), dt.date(2025, 1, 4)]

    out = tmp_path / "processed" / "hourly.parquet"
    hourly = cache.rebuild(raw=raw, out=out)
    assert out.exists()
    assert len(hourly) == 3 * 24  # Jan 3 has no prices; inner join keeps 3 full days
    assert sorted(hourly["date"].unique()) == ["2025-01-01", "2025-01-02", "2025-01-04"]
    assert hourly["ts_utc"].is_unique

    loaded = cache.load_hourly(out)
    assert len(loaded) == len(hourly)
    assert str(loaded["ts"].dt.tz) == "Europe/Madrid"
    assert loaded["ts"].iloc[0] == pd.Timestamp("2025-01-01 00:00", tz="Europe/Madrid")
    assert loaded["price_es"].iloc[0] == pytest.approx(134.49)


def test_load_source_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        cache.load_source("omie", raw=tmp_path)
