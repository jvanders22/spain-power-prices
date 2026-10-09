"""Headline findings, computed from the hourly table (used by the notebook and README)."""

from __future__ import annotations

import pandas as pd

from . import transform as t

WINDOWS = {
    "Oct 2024–Sep 2025": ("2024-10-01", "2025-09-30"),
    "Oct 2025–Sep 2026": ("2025-10-01", "2026-09-30"),
}


def window_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = {}
    for name, (a, b) in WINDOWS.items():
        g = t.filter_dates(df, a, b)
        if g.empty:
            continue
        k = t.kpis(g)
        mid = g[g["hour"].between(11, 16)]["price_es"].mean()
        eve = g[g["hour"].between(19, 22)]["price_es"].mean()
        rows[name] = {
            "hours": k["hours"],
            "avg_price": k["avg_price"],
            "zero_or_negative_hours": k["zero_or_negative_hours"],
            "negative_hours": k["negative_hours"],
            "pct_zero_or_negative": k["pct_zero_or_negative"],
            "renewables_share": k["avg_renewables_share"],
            "solar_share": t.share_of_demand(g, "solar"),
            "solar_capture": k["solar_capture"],
            "solar_capture_rate": k["solar_capture_rate"],
            "midday_11_16": mid,
            "evening_19_22": eve,
        }
    return pd.DataFrame(rows)


def headline(df: pd.DataFrame) -> dict:
    s = df.dropna(subset=["renewables_share"])
    low = s[s["renewables_share"] < 0.4]["price_es"].mean()
    high = s[s["renewables_share"] >= 0.8]["price_es"].mean()
    corr = s["price_es"].corr(s["renewables_share"])
    zero = df[df["price_es"] <= 0]
    midday_share = zero["hour"].between(10, 17).mean() if len(zero) else float("nan")
    by_month = df.assign(z=df["price_es"] <= 0).groupby("month")["z"].sum()
    cap = t.capture_prices(df)
    days = pd.PeriodIndex(cap.index, freq="M").days_in_month
    full = cap[cap["hours"] >= days * 24 - 1]  # complete months only (DST month has +/-1 hour)
    worst = full["solar_capture_rate"].idxmin() if len(full) else None
    return {
        "period": (df["date"].min(), df["date"].max()),
        "hours": len(df),
        "corr_price_renewables": corr,
        "price_share_lt40": low,
        "price_share_ge80": high,
        "zero_hours_total": int(len(zero)),
        "zero_hours_midday_share": midday_share,
        "zero_hours_peak_month": (by_month.idxmax(), int(by_month.max())),
        "worst_capture_month": (
            worst,
            float(full.loc[worst, "solar_capture_rate"]) if worst else float("nan"),
        ),
        "min_price": float(df["price_es"].min()),
        "windows": window_table(df),
    }
