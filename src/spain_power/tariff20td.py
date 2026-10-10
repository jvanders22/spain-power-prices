"""2.0TD access tariff: time-of-use periods and regulated energy terms (peninsular Spain).

Used only by the "Wholesale is not your bill" page to put the OMIE price in context. It is an
illustration, not a bill calculator: the full 2.0TD/3.0TD calculator lives in the companion
repo (jvanders22/spain-negative-price-alert, docs/tariffs.md).

Sources:

- Calendar: CNMC Circular 3/2020 (BOE-A-2020-1066). Peninsular 2.0TD energy periods on
  working days are P1 (punta) 10-14 and 18-22, P2 (llano) 8-10, 14-18 and 22-24, P3 (valle) 0-8.
  Saturdays, Sundays, 6 January and national holidays with a fixed date that cannot be moved
  are P3 all day. Movable holidays (Good Friday) and regional or local ones are normal days.
- Peajes 2026: CNMC Resolución of 18 Dec 2025 (BOE-A-2025-26348).
- Cargos 2026: Orden TED/1524/2025 (BOE-A-2025-26705), segment 1.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

PERIODS = {"P1": "punta", "P2": "llano", "P3": "valle"}

# Regulated energy terms for 2026, EUR/kWh.
PEAJES = {"P1": 0.033261, "P2": 0.016409, "P3": 0.000077}
CARGOS = {"P1": 0.064292, "P2": 0.012858, "P3": 0.003215}

# (month, day) of the fixed-date national holidays that count as P3.
FIXED_HOLIDAYS = frozenset({(1, 1), (1, 6), (5, 1), (8, 15), (10, 12), (11, 1), (12, 6), (12, 8), (12, 25)})

_P1_HOURS = frozenset({10, 11, 12, 13, 18, 19, 20, 21})


def tolls_and_charges() -> dict[str, float]:
    """Peajes + cargos per period in EUR/MWh."""
    return {p: round((PEAJES[p] + CARGOS[p]) * 1000, 3) for p in PERIODS}


def is_holiday(day: dt.date) -> bool:
    return (day.month, day.day) in FIXED_HOLIDAYS


def period(day: dt.date, hour: int) -> str:
    """2.0TD period of a local (Europe/Madrid) calendar day and clock hour 0-23."""
    if not 0 <= hour <= 23:
        raise ValueError(f"hour out of range: {hour}")
    if day.weekday() >= 5 or is_holiday(day) or hour < 8:
        return "P3"
    return "P1" if hour in _P1_HOURS else "P2"


def periods(df: pd.DataFrame) -> pd.Series:
    """Period of every row of an hourly frame, from its local ``date`` and ``hour`` columns.

    Both columns are Europe/Madrid wall-clock values, so DST days need no special handling:
    the repeated 02:00 hour in October is valle twice and the skipped one in March is absent.
    """
    d = pd.to_datetime(df["date"])
    hour = df["hour"]
    holiday = pd.Series(list(zip(d.dt.month, d.dt.day, strict=True)), index=df.index).isin(FIXED_HOLIDAYS)
    valle = (d.dt.dayofweek >= 5) | holiday | (hour < 8)
    out = pd.Series("P2", index=df.index)
    out[hour.isin(_P1_HOURS)] = "P1"
    out[valle] = "P3"
    return out


def summary(df: pd.DataFrame, threshold: float = 0.0) -> pd.DataFrame:
    """Per period: hours, average OMIE price, hours at or below ``threshold`` and their shares."""
    low = df["price_es"] <= threshold
    g = df.assign(period=periods(df), low=low).groupby("period")
    out = pd.DataFrame(
        {
            "hours": g.size(),
            "avg_price": g["price_es"].mean(),
            "low_hours": g["low"].sum().astype(int),
        }
    ).reindex(list(PERIODS))
    out["hours"] = out["hours"].fillna(0).astype(int)
    out["low_hours"] = out["low_hours"].fillna(0).astype(int)
    out["hours_share"] = out["hours"] / len(df)
    out["low_share"] = out["low_hours"] / low.sum() if low.any() else float("nan")
    out["tolls_and_charges"] = pd.Series(tolls_and_charges())
    return out
