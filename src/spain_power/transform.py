"""Pure transforms: join prices with the generation mix and compute the metrics."""

from __future__ import annotations

import numpy as np
import pandas as pd

TZ = "Europe/Madrid"
GRID_EVENT_DAYS = ["2025-04-28"]
RENEWABLE = ["wind", "solar_pv", "solar_thermal", "hydro_gen"]


CALIBRATED = ["wind", "solar_pv", "solar_thermal", "hydro_gen", "demand"]


def expected_hours(date: str) -> int:
    """Clock hours in a Europe/Madrid calendar day (23/24/25 on DST days)."""
    start = pd.Timestamp(date).tz_localize(TZ)
    end = (pd.Timestamp(date) + pd.Timedelta(days=1)).tz_localize(TZ)
    return int((end - start) / pd.Timedelta(hours=1))


def calibrate_daily(gen: pd.DataFrame, daily: pd.DataFrame | None) -> pd.DataFrame:
    """Scale each hourly generation series so its daily sum matches REE's official daily total.

    The real-time feed changed method on 2025-12-11 (solar PV jumps ~+23% overnight against
    REData; demand ~+3%), so the hourly *shape* comes from the real-time feed and the daily
    *level* from REData. Only days with every clock hour present and a valid REData total for
    every series are scaled and flagged ``calibrated = True``; anything else (typically the
    partial current day) keeps the real-time level.

    ``gen`` must carry a local ``date`` column and the :data:`CALIBRATED` columns.
    """
    df = gen.copy()
    for c in CALIBRATED:
        df[f"{c}_rt"] = df[c]
    df["calibrated"] = False
    if daily is None or daily.empty:
        return df
    daily = daily.assign(date=daily["date"].astype("string")).set_index("date")
    counts = df.groupby("date").size()
    complete = counts[[n == expected_hours(d) for d, n in counts.items()]].index
    sums = df.groupby("date")[CALIBRATED].sum().loc[complete]
    common = sums.index.intersection(daily.index)
    factors = pd.DataFrame(index=common)
    for c in CALIBRATED:
        target = daily[c].reindex(common) if c in daily else pd.Series(np.nan, index=common)
        src = sums.loc[common, c]
        f = (target / src).where((src > 0) & (target >= 0))
        # A series with zero real-time output can't be scaled (e.g. solar thermal on a dull
        # winter day while REData reports a few MWh); leave it as is. Demand must scale.
        if c != "demand":
            f = f.mask((src == 0) & target.notna(), 1.0)
        factors[c] = f
    ok = factors.notna().all(axis=1)
    factors = factors[ok]
    for c in CALIBRATED:
        df[c] = df[c] * df["date"].map(factors[c]).astype(float).fillna(1.0)
    df["calibrated"] = df["date"].isin(factors.index)
    return df


def build_hourly(prices: pd.DataFrame, gen: pd.DataFrame, daily: pd.DataFrame | None = None) -> pd.DataFrame:
    """Calibrate hourly generation, then inner-join it with hourly prices on UTC hour.

    ``daily`` (optional) holds REData daily MWh totals used by :func:`calibrate_daily`.
    Calibration runs on the generation table *before* the join so a missing price hour
    cannot distort the scaling of the remaining hours.
    """
    gen = gen.copy()
    gen["ts_utc"] = pd.to_datetime(gen["ts_utc"], utc=True)
    gen["date"] = gen["ts_utc"].dt.tz_convert(TZ).dt.date.astype("string")
    # REE reports hydro net of pumped-storage consumption; pumping is load, not negative output.
    gen["hydro_gen"] = gen["hydro"].clip(lower=0)
    gen = calibrate_daily(gen, daily)
    prices = prices.assign(ts_utc=pd.to_datetime(prices["ts_utc"], utc=True))
    df = prices.merge(gen, on="ts_utc", how="inner").sort_values("ts_utc")
    local = df["ts_utc"].dt.tz_convert(TZ)
    df["month"] = local.dt.strftime("%Y-%m")
    df["hour"] = local.dt.hour
    df["solar"] = df["solar_pv"] + df["solar_thermal"]
    df["renewables"] = df[RENEWABLE].sum(axis=1)
    # 28 Apr 2025 12:33 CEST: Iberian blackout. Day-ahead prices for that day were set the day
    # before and stay in the data, but demand collapsed to ~0, so shares are meaningless.
    df["grid_event"] = df["date"].isin(GRID_EVENT_DAYS) & (df["hour"] >= 12)
    dem = df["demand"].where((df["demand"] > 0) & ~df["grid_event"])
    df["renewables_share"] = (df["renewables"] / dem).clip(upper=1.5)
    df["solar_share"] = df["solar"] / dem
    df["wind_share"] = df["wind"] / dem
    return df.reset_index(drop=True)


def share_of_demand(df: pd.DataFrame, col: str) -> float:
    """Energy-weighted share of demand over valid hours (excludes grid-event hours)."""
    v = df[~df["grid_event"]] if "grid_event" in df else df
    return float(v[col].sum() / v["demand"].sum())


def filter_dates(df: pd.DataFrame, start, end) -> pd.DataFrame:
    d = pd.to_datetime(df["date"])
    return df[(d >= pd.Timestamp(start)) & (d <= pd.Timestamp(end))]


def share_buckets(df: pd.DataFrame, step: float = 0.1) -> pd.DataFrame:
    """Average price by renewables-share bucket (e.g. 0.3-0.4)."""
    edges = np.arange(0, 1.5 + step, step)
    b = pd.cut(df["renewables_share"], edges, right=False)
    g = df.groupby(b, observed=True)["price_es"].agg(["mean", "median", "count"])
    g.index = [f"{iv.left:.0%}-{iv.right:.0%}" for iv in g.index]
    return g


def negative_hours(df: pd.DataFrame, threshold: float = 0.0) -> pd.DataFrame:
    """Count of hours with price <= threshold, pivoted month x hour."""
    m = df.assign(flag=df["price_es"] <= threshold)
    return m.pivot_table(index="month", columns="hour", values="flag", aggfunc="sum", fill_value=0)


def capture_prices(df: pd.DataFrame, freq: str = "month") -> pd.DataFrame:
    """Baseload vs solar/wind generation-weighted (capture) prices per period.

    Computed on hourly values. Since 1 Oct 2025 OMIE clears in 15-minute periods, so this is an
    hourly proxy: within-hour co-movement of price and output is averaged away.

    capture = sum(price * gen) / sum(gen); capture rate = capture / baseload.
    """
    key = df[freq]

    def agg(g: pd.DataFrame) -> pd.Series:
        base = g["price_es"].mean()
        sol = (g["price_es"] * g["solar"]).sum() / g["solar"].sum()
        win = (g["price_es"] * g["wind"]).sum() / g["wind"].sum()
        return pd.Series(
            {
                "baseload": base,
                "solar_capture": sol,
                "wind_capture": win,
                "solar_capture_rate": sol / base if base else np.nan,
                "solar_share": share_of_demand(g, "solar"),
                "hours": len(g),
            }
        )

    return df.groupby(key).apply(agg, include_groups=False)


def kpis(df: pd.DataFrame) -> dict[str, float]:
    cap = capture_prices(df.assign(all="all"), "all").iloc[0]
    return {
        "avg_price": float(df["price_es"].mean()),
        "zero_or_negative_hours": int((df["price_es"] <= 0).sum()),
        "negative_hours": int((df["price_es"] < 0).sum()),
        "pct_zero_or_negative": float((df["price_es"] <= 0).mean()),
        "avg_renewables_share": share_of_demand(df, "renewables"),
        "solar_capture": float(cap["solar_capture"]),
        "solar_capture_rate": float(cap["solar_capture_rate"]),
        "hours": int(len(df)),
    }


def midday_depression(df: pd.DataFrame) -> pd.DataFrame:
    """Per month: midday (11-16h) average price minus evening (19-22h) average, plus solar share."""
    mid = df[df["hour"].between(11, 16)].groupby("month")["price_es"].mean()
    eve = df[df["hour"].between(19, 22)].groupby("month")["price_es"].mean()
    ss = df.groupby("month").apply(lambda g: share_of_demand(g, "solar"), include_groups=False)
    return pd.DataFrame({"midday": mid, "evening": eve, "spread": mid - eve, "solar_share": ss})
