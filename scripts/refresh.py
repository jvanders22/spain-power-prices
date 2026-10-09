"""Daily refresh: fetch missing days from OMIE + REE, rebuild data/processed/hourly.parquet.

Usage: python scripts/refresh.py [--start 2024-10-01] [--end YYYY-MM-DD]
Defaults: start = 24 months before today, end = tomorrow for OMIE (day-ahead), today for REE.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spain_power import cache  # noqa: E402


def main() -> int:
    today = dt.date.today()
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=dt.date.fromisoformat, default=dt.date(today.year - 2, today.month, 1))
    p.add_argument("--end", type=dt.date.fromisoformat, default=today)
    p.add_argument("--max-failed", type=int, default=10)
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    failed = {
        "omie": cache.fetch_range("omie", a.start, a.end + dt.timedelta(days=1)),
        "ree": cache.fetch_range("ree", a.start, a.end),
    }
    try:
        daily = cache.fetch_daily(a.start, a.end)
        logging.info("REData daily totals: %d days cached", len(daily))
    except Exception as e:  # noqa: BLE001 - calibration is best-effort; rebuild still works without it
        logging.warning("REData daily fetch failed, hourly data will be uncalibrated: %s", e)
    n_failed = sum(len(v) for v in failed.values())
    if n_failed:
        logging.warning("failed days: %s", {k: [str(d) for d in v] for k, v in failed.items() if v})
    if n_failed > a.max_failed:
        logging.error(
            "%d failed days > --max-failed %d; keeping the previous hourly table", n_failed, a.max_failed
        )
        return 1
    df = cache.rebuild(start=a.start, end=a.end + dt.timedelta(days=1))
    logging.info(
        "hourly table: %d rows, %s -> %s, %.1f%% of hours calibrated",
        len(df),
        df["date"].min(),
        df["date"].max(),
        100 * df["calibrated"].mean(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
