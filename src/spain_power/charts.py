"""Plotly figure builders shared by the dashboard, the notebook and the screenshot script.

Every function is pure: hourly frame (as produced by ``transform.build_hourly``) in, ``go.Figure`` out.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .transform import capture_prices, negative_hours, share_buckets

TEMPLATE = "plotly_white"
PRICE = "Day-ahead price (EUR/MWh)"
# Categorical slots, fixed order (validated light-mode palette): blue, orange, aqua, yellow, magenta, ...
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
INK = "#0b0b0b"


def _layout(fig: go.Figure, title: str, **kw) -> go.Figure:
    fig.update_layout(
        **{
            "template": TEMPLATE,
            "title": title,
            "margin": dict(l=60, r=20, t=60, b=50),
            "legend": dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1.0),
            "hovermode": "closest",
            **kw,
        }
    )
    return fig


def fig_price_vs_renewables(df: pd.DataFrame, step: float = 0.1) -> go.Figure:
    """Hourly price vs renewables share of demand, coloured by hour, with bucket means overlaid."""
    fig = go.Figure()
    fig.add_trace(
        go.Scattergl(
            x=df["renewables_share"],
            y=df["price_es"],
            mode="markers",
            name="Hourly price",
            marker=dict(
                size=5,
                opacity=0.35,
                color=df["hour"],
                colorscale="Twilight",  # cyclic: 23h sits next to 0h
                cmin=0,
                cmax=23,
                colorbar=dict(title="Hour", tickvals=[0, 6, 12, 18, 23]),
            ),
            customdata=df[["date", "hour"]],
            hovertemplate="%{customdata[0]} %{customdata[1]}h<br>Renewables %{x:.0%}"
            "<br>%{y:.2f} EUR/MWh<extra></extra>",
        )
    )
    b = share_buckets(df, step)
    if len(b):
        mid = [float(lbl.split("%")[0]) / 100 + step / 2 for lbl in b.index]
        fig.add_trace(
            go.Scatter(
                x=mid,
                y=b["mean"],
                mode="lines+markers",
                name=f"Mean price per {step:.0%} bucket",
                line=dict(color=INK, width=2),
                marker=dict(size=8, color=INK, line=dict(color="white", width=2)),
                customdata=list(zip(b.index, b["count"], strict=True)),
                hovertemplate="%{customdata[0]}: %{y:.2f} EUR/MWh (%{customdata[1]} h)<extra></extra>",
            )
        )
    _layout(fig, "Day-ahead price vs renewables share of demand")
    fig.update_xaxes(title="Renewables share of demand", tickformat=".0%")
    fig.update_yaxes(title=PRICE, zeroline=True)
    return fig


def fig_negative_heatmap(df: pd.DataFrame, threshold: float = 0.0) -> go.Figure:
    """Month x hour-of-day count of hours priced at or below ``threshold``."""
    p = negative_hours(df, threshold).reindex(columns=range(24), fill_value=0)
    fig = go.Figure(
        go.Heatmap(
            z=p.values,
            x=list(p.columns),
            y=list(p.index),
            colorscale="Blues",
            zmin=0,
            colorbar=dict(title="Hours"),
            xgap=2,
            ygap=2,
            hovertemplate="%{y} %{x}h: %{z} hours<extra></extra>",
        )
    )
    _layout(fig, f"Hours with day-ahead price ≤ {threshold:g} EUR/MWh")
    fig.update_xaxes(title="Hour of day (Europe/Madrid)", dtick=1)
    fig.update_yaxes(title="Month", type="category", autorange="reversed")
    return fig


def fig_capture_prices(df: pd.DataFrame) -> go.Figure:
    """Monthly baseload vs solar and wind capture (generation-weighted) prices."""
    c = capture_prices(df, freq="month")
    fig = go.Figure()
    for col, name, color in [
        ("baseload", "Baseload", SERIES[0]),
        ("solar_capture", "Solar capture", SERIES[1]),
        ("wind_capture", "Wind capture", SERIES[2]),
    ]:
        fig.add_trace(
            go.Scatter(
                x=list(c.index),
                y=c[col],
                mode="lines+markers",
                name=name,
                line=dict(color=color, width=2),
                marker=dict(size=8, color=color),
                hovertemplate=f"{name}: %{{y:.2f}} EUR/MWh<extra></extra>",
            )
        )
    _layout(fig, "Baseload vs solar and wind capture price, monthly", hovermode="x unified")
    fig.update_xaxes(title="Month", type="category")
    fig.update_yaxes(title="Price (EUR/MWh)")
    return fig


def profile_windows(df: pd.DataFrame) -> pd.Series:
    """Label each row with a 12-month window ending at the latest month, e.g. 'Oct 2025–Sep 2026'."""
    months = pd.PeriodIndex(df["month"].astype(str), freq="M")
    last = months.max()
    if "date" in df and months.min() < last:
        # Anchor on the latest *complete* month so windows compare like with like.
        days_in_last = df.loc[months == last, "date"].nunique()
        if days_in_last < last.days_in_month:
            last = last - 1
    back = (last.ordinal - months.asi8) // 12
    back = np.where(months.asi8 > last.ordinal, -1, back)
    labels = {}
    for k in np.unique(back):
        if k < 0:
            labels[k] = (None, False)
            continue
        end = last - 12 * int(k)
        start = max(end - 11, months.min())
        full = (end - start).n == 11
        labels[k] = (f"{start.strftime('%b %Y')}–{end.strftime('%b %Y')}", full)
    has_full = any(f for _, f in labels.values())
    lab = pd.Series([labels[k][0] for k in back], index=df.index)
    keep = pd.Series([labels[k][1] or not has_full for k in back], index=df.index)
    return lab.where(keep)


def fig_hourly_profile(df: pd.DataFrame) -> go.Figure:
    """Average day-ahead price by hour of day, one line per 12-month window.

    Windows are counted back from the latest month in ``df`` so every line covers a full
    seasonal cycle (calendar years would compare a partial year with a full one). A trailing
    partial window shorter than 12 months is dropped when at least one full window exists.
    """
    year = profile_windows(df).rename("year")
    prof = df.groupby([year, "hour"])["price_es"].mean().unstack("year")
    fig = go.Figure()
    for i, y in enumerate(prof.columns):
        color = SERIES[i % len(SERIES)]
        fig.add_trace(
            go.Scatter(
                x=list(prof.index),
                y=prof[y],
                mode="lines+markers",
                name=str(y),
                line=dict(color=color, width=2),
                marker=dict(size=8, color=color),
                hovertemplate=f"{y}: %{{y:.2f}} EUR/MWh<extra></extra>",
            )
        )
    _layout(fig, "Average day-ahead price by hour of day", hovermode="x unified")
    fig.update_xaxes(title="Hour of day (Europe/Madrid)", dtick=1, range=[-0.5, 23.5])
    fig.update_yaxes(title=PRICE)
    return fig
