"""Export the series and headline numbers used by the Remotion explainer (video/src/data.json).

Everything shown on screen comes from data/processed/hourly.parquet via spain_power.findings,
so the video never carries hand-typed numbers.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from spain_power import findings
from spain_power import transform as t

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "video" / "src" / "data.json"


def _r(x: float, nd: int = 1) -> float:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        raise ValueError("unexpected NaN in video export")
    return round(float(x), nd)


def main() -> None:
    df = pd.read_parquet(ROOT / "data" / "processed" / "hourly.parquet")
    h = findings.headline(df)
    w = h["windows"]
    years = []
    for label, (a, b) in findings.WINDOWS.items():
        g = t.filter_dates(df, a, b)
        prof = g.groupby("hour")["price_es"].mean().reindex(range(24))
        if prof.isna().any():
            raise ValueError(f"missing hours in profile for {label}")
        col = w[label]
        years.append(
            {
                "label": label,
                "start": a,
                "end": b,
                "hours": int(col["hours"]),
                "hourly_price": [_r(v) for v in prof.tolist()],  # EUR/MWh, Europe/Madrid clock hour
                "midday_11_16": _r(col["midday_11_16"]),
                "evening_19_22": _r(col["evening_19_22"]),
                "solar_capture_rate": _r(col["solar_capture_rate"] * 100, 0),
                "solar_share": _r(col["solar_share"] * 100, 1),
                "zero_or_negative_hours": int(col["zero_or_negative_hours"]),
            }
        )
    zero_total = h["zero_hours_total"]
    out = {
        "source": "OMIE day-ahead (Spain) + REE generation, data/processed/hourly.parquet",
        "period": list(h["period"]),
        "years": years,
        "all_hours": h["hours"],
        "zero_or_negative_hours": zero_total,
        "pct_zero_or_negative": _r(zero_total / h["hours"] * 100, 1),
        "zero_hours_midday_pct": _r(h["zero_hours_midday_share"] * 100, 0),  # 10:00-17:59
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
