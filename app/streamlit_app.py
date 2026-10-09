"""Streamlit dashboard: Spanish day-ahead power prices vs renewables.

Run from the repo root: ``streamlit run app/streamlit_app.py``
(reads data/processed/hourly.parquet; build it with ``python scripts/refresh.py``).
Set ``SPAIN_POWER_HOURLY`` to point at a different hourly parquet file.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spain_power import charts, transform  # noqa: E402
from spain_power.cache import PROCESSED, load_hourly  # noqa: E402

DATA_PATH = Path(os.environ.get("SPAIN_POWER_HOURLY", PROCESSED))

st.set_page_config(page_title="Spanish power prices vs renewables", layout="wide")


@st.cache_data(show_spinner="Loading hourly data…")
def load(path: str, mtime: float) -> pd.DataFrame:  # mtime busts the cache after a refresh
    return load_hourly(Path(path))


st.title("Spanish power prices vs renewables")

if not DATA_PATH.exists():
    st.error(f"No data at `{DATA_PATH}`. Run `python scripts/refresh.py` first.")
    st.stop()

data = load(str(DATA_PATH), DATA_PATH.stat().st_mtime)
d_min = pd.to_datetime(data["date"]).min().date()
d_max = pd.to_datetime(data["date"]).max().date()
st.caption(
    f"OMIE day-ahead marginal price (Spain) and REE peninsular generation mix, hourly, "
    f"{d_min:%d %b %Y} – {d_max:%d %b %Y}."
)

with st.sidebar:
    st.header("Filters")
    picked = st.date_input("Date range", value=(d_min, d_max), min_value=d_min, max_value=d_max)
    threshold = st.number_input("Zero/negative price threshold (EUR/MWh)", value=0.0, step=1.0)

# While the user is mid-selection date_input returns a 1-tuple.
start, end = (picked[0], picked[-1]) if isinstance(picked, tuple | list) else (picked, picked)
df = transform.filter_dates(data, start, end)
if df.empty:
    st.warning("No hourly data in the selected date range.")
    st.stop()

k = transform.kpis(df)
n_low = int((df["price_es"] <= threshold).sum())
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Avg price (€/MWh)", f"{k['avg_price']:.1f}")
c2.metric(
    f"Hours ≤ {threshold:g} EUR/MWh",
    f"{n_low:,}",
    help=f"{n_low / len(df):.1%} of {len(df):,} hours in the selected range",
)
c3.metric("Renewables share", f"{k['avg_renewables_share']:.1%}")
c4.metric("Solar capture (€/MWh)", f"{k['solar_capture']:.1f}")
c5.metric(
    "Solar capture rate",
    f"{k['solar_capture_rate']:.0%}",
    help="Solar generation-weighted price divided by the simple average (baseload) price",
)
st.caption(f"{n_low / len(df):.1%} of hours in the selected range cleared at or below {threshold:g} EUR/MWh.")

tab_scatter, tab_neg, tab_solar, tab_data = st.tabs(
    ["Price vs renewables", "Zero/negative hours", "Solar cannibalisation", "Data"]
)

with tab_scatter:
    st.plotly_chart(charts.fig_price_vs_renewables(df))

with tab_neg:
    st.plotly_chart(charts.fig_negative_heatmap(df, threshold))

with tab_solar:
    st.plotly_chart(charts.fig_capture_prices(df))
    st.plotly_chart(charts.fig_hourly_profile(df))

with tab_data:
    out = df.drop(columns=["ts"], errors="ignore")
    st.caption(f"{len(out):,} hourly rows in range; showing up to 500.")
    st.dataframe(out.head(500), hide_index=True)
    st.download_button(
        "Download filtered hourly CSV",
        out.to_csv(index=False).encode("utf-8"),
        file_name=f"spain_power_hourly_{start:%Y%m%d}_{end:%Y%m%d}.csv",
        mime="text/csv",
    )

st.divider()
st.caption("Data: OMIE (omie.es) and Red Eléctrica (ree.es). Not affiliated.")
