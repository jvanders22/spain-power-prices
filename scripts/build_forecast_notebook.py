"""Regenerate notebooks/forecast.ipynb (unexecuted). Execute with:
jupyter nbconvert --to notebook --execute --inplace notebooks/forecast.ipynb

The notebook only reads the committed backtest outputs (docs/forecast_results.json and
data/processed/forecast_backtest.parquet); it does not rerun the backtest.
"""

import nbformat as nbf

nb = nbf.v4.new_notebook()
C = []


def md(s):
    return C.append(nbf.v4.new_markdown_cell(s))


def code(s):
    return C.append(nbf.v4.new_code_cell(s))


md("""# D+2 forecast of zero-price hours: backtest

At about 13:00 Europe/Madrid on day D, for each clock hour of delivery day D+2: the probability that the OMIE day-ahead price for Spain clears at or below 0 EUR/MWh.

**What the forecast may use** (`spain_power.forecast.available_at`)
- Prices through the end of D+1. The day-ahead result for D+1 is published around 13:00 on D and is treated as known.
- REE generation and demand through the end of D-1 only. The real-time feed for D is half a day short at 13:00, so D is left out.
- Weather forecasts issued 72 hours before each target hour (Open-Meteo Previous Runs API, `_previous_day3` fields). For the last hour of D+2 that is 23:00 on D-1. The 48-hour fields would come from runs started after 13:00 on D for every afternoon hour, so they are not used. Observed or reanalysis weather is never used.
- The calendar of D+2.

**Backtest.** Rolling origin, one forecast per day, expanding training window, weekly retrain, at least 90 training days. The model is scikit-learn's `HistGradientBoostingClassifier` with settings fixed before the run. Baselines: *same as D+1*, *same hour last week*, and a month × hour *climatology* from the training window.

This notebook reads the outputs of `python scripts/backtest_forecast.py` (about 10 minutes); it does not rerun it. Weather forecasts by Open-Meteo.com (CC BY 4.0).""")
code("""import sys
from pathlib import Path

ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd
import plotly.io as pio

from spain_power import case_study, charts, forecast

pio.renderers.default = "png"  # static images so the notebook renders on GitHub
pd.set_option("display.float_format", "{:,.3f}".format)

res = forecast.load_results(ROOT / "docs" / "forecast_results.json")
bt = pd.read_parquet(ROOT / "data" / "processed" / "forecast_backtest.parquet")
m = res["meta"]
COLS = ["precision", "recall", "f1", "brier", "day_exact", "day_exact_zero_days", "day_any"]


def table(block):
    return pd.DataFrame({res["labels"][k]: v for k, v in block.items() if v}).T[COLS].astype(float)


print(f"{m['target_days']} target days, {m['first_target']} to {m['last_target']}; data through {m['data_end']}")
print(f"{m['zero_hours']:,} zero hours of {m['hours']:,} ({m['zero_hours'] / m['hours']:.1%}); {m['retrains']} retrains")
print(f"{sum(len(v) for v in m['features'].values())} features; weather lead: {m['weather_lead']}")""")
md("""## 1. Model vs baselines

The positive class is price ≤ 0. `brier` is the mean squared error of the probability (lower is better); the two price baselines count as probabilities of 0 or 1. `day_exact` is the share of days where the predicted set of zero hours equals the actual set. A day with no zero hours is matched by predicting none, so `day_exact_zero_days` gives the same share over days that had at least one. `day_any` is the share of days where "at least one zero hour" was called correctly.""")
code("""print(case_study.forecast_verdict(res))
table(res["overall"])""")
code("""for key, d in {**res["vs_baselines"], "model_no_weather": res["vs_no_weather"]}.items():
    print(f"model minus {key}: F1 {d['f1_diff']:+.3f} (95% {d['f1_ci'][0]:+.3f} to {d['f1_ci'][1]:+.3f}), "
          f"Brier {d['brier_diff']:+.4f} (95% {d['brier_ci'][0]:+.4f} to {d['brier_ci'][1]:+.4f})")
print(f"intervals: {res['vs_baselines']['same_as_d1']['resamples']:,} resamples of whole days")""")
md(
    """The stored hourly forecasts reproduce the table: the same metrics, recomputed here from `forecast_backtest.parquet`."""
)
code("""check = pd.DataFrame({res["labels"][k]: forecast.evaluate(bt, pred, prob) for k, (_, pred, prob) in forecast.METHODS.items()}).T[COLS].astype(float)
assert (check - table(res["overall"])).abs().max().max() < 1e-4
print(f"tuned threshold: median {m['tuned_threshold_median']:.2f}, range {m['tuned_threshold_range'][0]:.2f} to {m['tuned_threshold_range'][1]:.2f}")""")
md("## 2. Calibration")
code("""charts.fig_reliability(res["reliability"]).show(width=900, height=500)""")
code("""pd.DataFrame(res["reliability"]).set_index("bin")""")
md(
    "## 3. By season\nSeason of the target day. Zero hours are a spring, midday event, so the other seasons have few positives and noisier scores."
)
code(
    """charts.fig_forecast_seasons(res["by_season"], res["labels"], ["model", "same_as_d1", "last_week", "climatology"]).show(width=900, height=450)"""
)
code("""pd.concat({s: table(b) for s, b in res["by_season"].items() if b.get("model")})""")
md("""## 4. Where it fails

- **Onset day:** at least one zero hour after seven days without any. Both price baselines miss these by construction.
- **Streak break:** D+1 had zero hours (so *same as D+1* predicts some) but D+2 has none.
- **Hour groups:** zero hours outside midday are few and mostly wind-driven.""")
code("""f = res["failures"]
o, b = f["onset"], f["streak_break"]
print(f"Onset days: {o['days']} ({o['zero_hours']} zero hours). Model flagged {o['model_days_flagged']} days, hour recall {o['model_recall']:.0%}.")
print(f"Streak breaks: {b['days']} days. False hours: model {b['model_false_hours']} (on {b['model_days_flagged']} days), same as D+1 {b['d1_false_hours']}.")
pd.DataFrame(f["hour_groups"]).T""")
md(
    "Three days picked by rule: the onset day with the most missed hours, the streak break with the most hours wrongly called, and the day with the most missed night hours. The `forecast_*` values are what the model saw (72-hour-ahead daily means, with the day before in `*_prev`); the `*_share` values are what then happened (share of demand)."
)
code("""pd.DataFrame(f["examples"]).set_index("date").T""")
code("""for e in f["examples"]:
    day = bt[bt["date"] == e["date"]].set_index("hour")
    print(e["date"], e["kind"])
    print(day.loc[day["y"] | day["pred_model"] | day["base_d1"], ["price", "p_model", "pred_model", "base_d1", "base_week"]].round(3).to_string(), "\\n")""")
md("""## 5. Limits

- **One path.** A single rolling backtest; the intervals above cover day-to-day sampling only, not model or period choice.
- **Revised inputs.** The REE figures are today's values, scaled to official daily totals that REE revises for weeks. A live forecast would see earlier versions.
- **Hourly target.** Since 1 Oct 2025 the market clears in 15-minute periods and the target is the hourly mean, so a quarter-hour at or below zero inside a positive hour is not counted.
- **Weather timing.** The 72-hour lead rests on Open-Meteo's description of its archived forecasts; the archive mixes weather models and may not match what a user saw live.
- **No live run yet.** These are backtest results, not a record of forecasts made in real time.""")
nb["cells"] = C
nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
nbf.write(nb, "notebooks/forecast.ipynb")
