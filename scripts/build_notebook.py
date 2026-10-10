"""Regenerate notebooks/analysis.ipynb (unexecuted). Execute with:
jupyter nbconvert --to notebook --execute --inplace notebooks/analysis.ipynb
"""

import nbformat as nbf

nb = nbf.v4.new_notebook()
C = []


def md(s):
    return C.append(nbf.v4.new_markdown_cell(s))


def code(s):
    return C.append(nbf.v4.new_code_cell(s))


md("""# Spanish power prices vs renewables

Analysis of the Spanish day-ahead electricity market against the peninsular generation mix.

**Questions**
1. How does the day-ahead price move with the renewables share of demand?
2. When do zero and negative prices happen (month × hour)?
3. Solar cannibalisation: how far below the average price does solar's output clear, and is it getting worse?

**Data** (no API token needed; see README for details and licences)
- Prices: OMIE day-ahead marginal price for Spain (`marginalpdbc` daily files). Since 1 Oct 2025 the market clears in 15-minute periods; they are averaged to clock hours here.
- Generation and demand: REE real-time peninsular feed (5-minute resolution, averaged to hours), calibrated so each day's totals match REE's official daily figures from the REData API. The real-time feed changed method on 11 Dec 2025 (solar PV jumped ~23% overnight versus REData), and calibration removes that break.
- *Renewables share* = (wind + solar PV + solar thermal + hydro output) / peninsular demand, per hour. It can exceed 100% when Spain exports or pumps.

Refresh the data with `python scripts/refresh.py`; this notebook reads `data/processed/hourly.parquet`.""")
code("""import sys
from pathlib import Path

ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd
import plotly.io as pio

from spain_power import cache, charts, findings, transform as t

pio.renderers.default = "png"  # static images so the notebook renders on GitHub
pd.set_option("display.float_format", "{:,.2f}".format)

df = cache.load_hourly(ROOT / "data" / "processed" / "hourly.parquet")
h = findings.headline(df)
print(f"{len(df):,} hours from {df['date'].min()} to {df['date'].max()}")
print(f"calibrated to REData daily totals: {df['calibrated'].mean():.1%} of hours")
df[["ts", "price_es", "demand", "solar", "wind", "renewables_share"]].tail()""")
md("## 0. Two comparable 12-month windows\nOctober–September windows so both cover a full seasonal cycle.")
code("""w = findings.window_table(df)
w.style.format("{:,.3f}")""")
md("## 1. Price vs renewables share")
code("""charts.fig_price_vs_renewables(df).show(width=1000, height=550)""")
code("""buckets = t.share_buckets(df.dropna(subset=["renewables_share"]))
print(f"Pearson correlation, hourly price vs renewables share: {h['corr_price_renewables']:.2f}")
print(f"Mean price when renewables < 40% of demand: {h['price_share_lt40']:.1f} EUR/MWh")
print(f"Mean price when renewables >= 80% of demand: {h['price_share_ge80']:.1f} EUR/MWh")
buckets""")
md("""Prices fall steadily as renewables cover more of demand, and the median collapses to around zero once the share passes ~80%. The fall is not linear: below ~40% gas (combined cycle) sets the price, while above ~70% the price is set by renewables bidding near zero.

The hours from 12:00 on 28 Apr 2025 (the Iberian blackout) are kept in the price series but excluded from share calculations, because measured demand collapsed to near zero.""")
md("## 2. Zero and negative price hours")
code("""charts.fig_negative_heatmap(df).show(width=1000, height=600)""")
code("""z = df[df["price_es"] <= 0]
print(f"Hours at or below 0 EUR/MWh: {len(z):,} of {len(df):,} ({len(z)/len(df):.1%})")
print(f"  of which strictly negative: {(df['price_es'] < 0).sum():,}; lowest hourly price {df['price_es'].min():.2f} EUR/MWh")
print(f"Share of those hours between 10:00 and 17:59: {h['zero_hours_midday_share']:.0%}")
print(f"Peak month: {h['zero_hours_peak_month'][0]} with {h['zero_hours_peak_month'][1]} hours")
t.negative_hours(df).sum(axis=1).rename("hours <= 0").to_frame().T""")
md(
    """Zero and negative hours are a spring, midday phenomenon: solar peaks while demand is mild, and hydro and wind are often strong too. February 2026 stands out with zero-price hours overnight as well as at midday. The cell below shows why: wind covered a much larger share of night-time demand than a year earlier. Negative prices in Spain stay shallow (a few EUR/MWh below zero) because most renewables are not paid per MWh in the day-ahead market and simply curtail."""
)
code("""night = df[df["hour"].between(1, 5)]
for m in ["2025-02", "2026-02"]:
    g = night[night["month"] == m]
    print(f"{m}, 01-05h: mean price {g['price_es'].mean():.1f} EUR/MWh, wind {g['wind'].sum()/g['demand'].sum():.0%} "
          f"and hydro {g['hydro_gen'].sum()/g['demand'].sum():.0%} of demand")""")
md("## 3. Solar cannibalisation")
code("""charts.fig_capture_prices(df).show(width=1000, height=550)""")
code("""cap = t.capture_prices(df)
cap[["baseload", "solar_capture", "wind_capture", "solar_capture_rate", "solar_share"]]""")
code("""charts.fig_hourly_profile(df).show(width=1000, height=550)""")
code("""md = t.midday_depression(df)
md""")
code("""for name, col in w.items():
    print(f"{name}: solar share {col['solar_share']:.1%}, solar capture rate {col['solar_capture_rate']:.0%}, "
          f"midday (11-16h) {col['midday_11_16']:.1f} vs evening (19-22h) {col['evening_19_22']:.1f} EUR/MWh")
wm, wr = h["worst_capture_month"]
print(f"Worst month for solar: {wm}, capture rate {wr:.0%} of baseload")""")
md("""Solar is sold mostly in the hours when solar itself pushes the price down, so its generation-weighted (capture) price sits far below baseload. That gap widened as solar's share of demand grew between the two windows. Midday prices fell while evening prices rose, which is the duck-curve spread that batteries and flexible demand earn from. Wind's capture price stays close to baseload because wind output is spread across the day.

**Caveats.** These are day-ahead prices only (no intraday or balancing markets, no capacity or ancillary revenues). REE real-time values are provisional, and the daily calibration fixes daily levels but not intra-day shape errors. The renewables share uses peninsular demand and ignores the Balearic and Canary systems.""")
nb["cells"] = C
nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
nbf.write(nb, "notebooks/analysis.ipynb")
