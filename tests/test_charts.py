from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import pytest

from spain_power import charts


@pytest.mark.parametrize(
    "build",
    [
        charts.fig_price_vs_renewables,
        charts.fig_negative_heatmap,
        lambda df: charts.fig_negative_heatmap(df, threshold=50.0),
        charts.fig_capture_prices,
        charts.fig_hourly_profile,
    ],
)
def test_figures_have_traces(hourly, build):
    fig = build(hourly)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) >= 1
    assert fig.layout.title.text


def test_price_vs_renewables_overlay(hourly):
    fig = charts.fig_price_vs_renewables(hourly)
    assert len(fig.data) == 2
    assert fig.layout.xaxis.tickformat == ".0%"
    assert "EUR/MWh" in fig.layout.yaxis.title.text


def test_heatmap_full_hour_grid(hourly):
    fig = charts.fig_negative_heatmap(hourly, threshold=60.0)
    hm = fig.data[0]
    assert list(hm.x) == list(range(24))
    assert list(hm.y) == ["2024-12", "2025-01", "2025-02"]


def test_capture_and_profile_series(hourly):
    cap = charts.fig_capture_prices(hourly)
    assert [t.name for t in cap.data] == ["Baseload", "Solar capture", "Wind capture"]
    prof = charts.fig_hourly_profile(hourly)
    assert [t.name for t in prof.data] == ["Dec 2024–Feb 2025"]
    assert all(len(t.x) == 24 for t in prof.data)


def test_profile_windows_full_years_drop_partial_tail():
    days = pd.date_range("2024-10-01", "2026-10-09", freq="D")
    df = pd.DataFrame({"date": days.strftime("%Y-%m-%d"), "month": days.strftime("%Y-%m")})
    lab = charts.profile_windows(df)
    assert set(lab.dropna()) == {"Oct 2024–Sep 2025", "Oct 2025–Sep 2026"}
    assert lab.isna().sum() == 9  # the 9 days of partial Oct 2026 are excluded
