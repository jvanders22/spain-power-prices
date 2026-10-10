"""Run the D+2 zero-hour forecast backtest and write its results.

Manual step (needs scikit-learn from the dev extras; a few minutes):

    python scripts/backtest_forecast.py

Reads ``data/processed/hourly.parquet`` and the Open-Meteo forecasts cached under
``data/weather`` (missing quarters are fetched unless ``--offline``), then writes
``data/processed/forecast_backtest.parquet`` (one row per forecast hour) and
``docs/forecast_results.json`` (every metric the site, case study and notebook show).
Deterministic: fixed seed, no timestamps in the outputs. Afterwards run
``python scripts/build_case_study.py`` and ``python scripts/build_site.py``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spain_power import cache, forecast, weather  # noqa: E402

COLUMNS = ["precision", "recall", "f1", "brier", "day_exact", "day_exact_zero_days", "day_any"]


def metrics_table(block: dict, labels: dict) -> pd.DataFrame:
    rows = {labels[k]: {c: v.get(c) for c in COLUMNS} for k, v in block.items() if v}
    return pd.DataFrame(rows).T[COLUMNS].astype(float)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=cache.PROCESSED)
    ap.add_argument("--weather", type=Path, default=weather.CACHE)
    ap.add_argument("--offline", action="store_true", help="fail instead of fetching missing weather")
    ap.add_argument("--out", type=Path, default=forecast.BACKTEST)
    ap.add_argument("--results", type=Path, default=forecast.RESULTS)
    args = ap.parse_args(argv)

    hourly = cache.load_hourly(args.data).drop(columns=["ts"])
    # UTC days spanning the local days of the table.
    start = dt.date.fromisoformat(hourly["date"].min()) - dt.timedelta(days=1)
    end = dt.date.fromisoformat(hourly["date"].max())
    wx = weather.aggregate(weather.load(start, end, cache=args.weather, fetch=not args.offline))

    table = forecast.feature_table(hourly, wx)
    bt = forecast.backtest(table)
    results = forecast.summarise(bt, table, hourly)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    bt.to_parquet(args.out, index=False)
    args.results.parent.mkdir(parents=True, exist_ok=True)
    args.results.write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    m = results["meta"]
    pd.set_option("display.width", 200, "display.float_format", "{:.3f}".format)
    print(
        f"{m['target_days']} target days, {m['first_target']} to {m['last_target']}: "
        f"{m['zero_hours']:,} zero hours of {m['hours']:,}; {m['retrains']} retrains"
    )
    print("\nOverall")
    print(metrics_table(results["overall"], results["labels"]).to_string())
    for season, block in results["by_season"].items():
        if block["model"]:
            print(f"\n{season}: {block['model']['zero_hours']} zero hours on {block['model']['days']} days")
            print(metrics_table(block, results["labels"]).to_string())
    print(f"\nwrote {args.out}\nwrote {args.results}")


if __name__ == "__main__":
    main()
