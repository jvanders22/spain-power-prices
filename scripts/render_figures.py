"""Render the dashboard charts to PNG for the README (needs kaleido + a local Chrome)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spain_power import cache, charts  # noqa: E402

OUT = ROOT / "docs" / "img"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df = cache.load_hourly()
    figs = {
        "price_vs_renewables": charts.fig_price_vs_renewables(df),
        "negative_hours_heatmap": charts.fig_negative_heatmap(df),
        "capture_prices": charts.fig_capture_prices(df),
        "hourly_profile": charts.fig_hourly_profile(df),
    }
    for name, fig in figs.items():
        path = OUT / f"{name}.png"
        fig.write_image(path, width=1100, height=600, scale=2)
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
