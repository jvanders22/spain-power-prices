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
