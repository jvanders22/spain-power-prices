from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from spain_power import ree
from spain_power.transform import build_hourly

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_text():
    def read(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return read


def synthetic_inputs(
    start: str = "2024-12-01", end: str = "2025-02-28 23:00"
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Hourly prices + generation (UTC-keyed, spanning whole local days) with a solar bell curve
    that depresses midday prices."""
    ts = pd.date_range(start, end, freq="h", tz="Europe/Madrid").tz_convert("UTC")
    rng = np.random.default_rng(0)
    hour = ts.tz_convert("Europe/Madrid").hour.to_numpy()
    solar = np.clip(np.sin((hour - 7) / 11 * np.pi), 0, None) * 15000
    wind = rng.uniform(2000, 12000, len(ts))
    demand = np.full(len(ts), 28000.0)
    price = 120 - 0.006 * (solar + wind) + rng.normal(0, 5, len(ts))
    prices = pd.DataFrame({"ts_utc": ts, "price_es": price, "price_pt": price})
    gen = pd.DataFrame({"ts_utc": ts, **{c: 0.0 for c in ree.FIELDS.values()}})
    gen["demand"] = demand
    gen["wind"] = wind
    gen["solar_pv"] = solar * 0.95
    gen["solar_thermal"] = solar * 0.05
    gen["hydro"] = np.where(hour < 6, -1500.0, 3000.0)  # night-time pumping
    return prices, gen


@pytest.fixture
def hourly() -> pd.DataFrame:
    return build_hourly(*synthetic_inputs())


def synthetic_weather(hourly: pd.DataFrame) -> pd.DataFrame:
    """Aggregated "forecasts" (``weather.aggregate`` columns) that track the synthetic output."""
    rng = np.random.default_rng(1)
    n = len(hourly)
    wind = hourly["wind"].to_numpy() / 1000 + rng.normal(0, 0.5, n)
    return pd.DataFrame(
        {
            "ts_utc": hourly["ts_utc"].to_numpy(),
            "wx_rad": hourly["solar"].to_numpy() / 20,
            "wx_wind": wind,
            "wx_wind3": np.clip(wind, 0, 12) ** 3,
            "wx_temp": 15 + rng.normal(0, 3, n),
        }
    ).assign(ts_utc=lambda d: pd.to_datetime(d["ts_utc"], utc=True))


@pytest.fixture(scope="session")
def forecast_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Six months of synthetic hourly data and matching weather, for the forecast tests."""
    hourly = build_hourly(*synthetic_inputs("2024-10-01", "2025-03-31 23:00"))
    return hourly, synthetic_weather(hourly)


@pytest.fixture
def forecast_results() -> dict:
    """A small backtest results file: ``forecast.summarise`` on the synthetic frames."""
    import json

    return json.loads((FIXTURES / "forecast_results_small.json").read_text(encoding="utf-8"))
