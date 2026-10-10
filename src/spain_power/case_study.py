"""Case study text, generated from the hourly table.

One source for three places: ``docs/case_study.md``, the README section between the
``case-study`` markers and the static site's case-study page. Every number comes from
:mod:`spain_power.findings` or :mod:`spain_power.transform` at generation time, except the
forecast section, whose numbers come from the committed backtest results
(``docs/forecast_results.json``, written by ``scripts/backtest_forecast.py``).
"""

from __future__ import annotations

import re

import pandas as pd

from . import findings, forecast
from . import transform as t

START = "<!-- case-study:start -->"
END = "<!-- case-study:end -->"
REPO_URL = "https://github.com/jvanders22/spain-power-prices"
SITE_URL = "https://jvanders22.github.io/spain-power-prices"
COMPANION_URL = "https://github.com/jvanders22/spain-negative-price-alert"
# How the baselines are named inside a sentence.
BASELINE_NAMES = {
    "same_as_d1": '"same as D+1"',
    "last_week": '"same hour last week"',
    "climatology": "climatology",
}


def _day(date: str) -> str:
    ts = pd.Timestamp(date)
    return f"{ts.day} {ts:%b %Y}"


def _month(month: str) -> str:
    return f"{pd.Timestamp(month + '-01'):%B %Y}"


def _moved(a: float, b: float, fmt: str) -> str:
    """'rose from A to B' / 'fell from A to B' / 'stayed at A', judged on the formatted values."""
    fa, fb = format(a, fmt), format(b, fmt)
    if fa == fb:
        return f"stayed at {fa}"
    return f"{'rose' if b > a else 'fell'} from {fa} to {fb}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def forecast_verdict(results: dict) -> str:
    """One sentence: does the model beat the baselines on F1 and Brier score, with the numbers."""
    o = results["overall"]
    by_f1 = results["best_baseline"]["f1"]
    by_brier = results["best_baseline"]["brier"]
    numbers = (
        f"F1 for zero hours is {o['model']['f1']:.2f} against {o[by_f1]['f1']:.2f} for the best "
        f"baseline ({BASELINE_NAMES[by_f1]}), and the Brier score is {o['model']['brier']:.3f} "
        f"against {o[by_brier]['brier']:.3f} ({BASELINE_NAMES[by_brier]}; lower is better)"
    )
    if forecast.beats_baselines(results):
        return f"The model beats all three baselines on this backtest: {numbers}."
    return f"The model does not beat every baseline on this backtest: {numbers}."


def forecast_section(results: dict) -> str:
    """The forecast paragraph of the case study, from the backtest results."""
    m, o, f = results["meta"], results["overall"], results["failures"]
    model, nowx, d1 = o["model"], o["model_no_weather"], o["same_as_d1"]
    helps = model["f1"] > nowx["f1"] and model["brier"] < nowx["brier"]
    seasons = {s: b["model"]["f1"] for s, b in results["by_season"].items() if b.get("model")}
    weakest = min(seasons, key=seasons.get)
    tuned = o["model_tuned"]
    night = f["hour_groups"]["Night (20:00–07:59)"]
    night_vs = ""
    if night["model_recall"] is not None and night["d1_recall"] is not None:
        side = "below" if night["model_recall"] < night["d1_recall"] else "against"
        night_vs = f", {side} the {_pct(night['d1_recall'])} of {BASELINE_NAMES['same_as_d1']}"
    return f"""## D+2 forecast of zero-price hours

A prototype forecasts, at 13:00 on day D, the probability that each hour of day D+2 clears at
or below 0 EUR/MWh. It is a gradient-boosted tree model on prices through D+1, REE generation
and demand through D-1, the calendar of D+2 and weather forecasts issued 72 hours ahead
(Open-Meteo), with every input cut at what was already published. The backtest is
rolling-origin: one forecast per day for {m["target_days"]:,} days ({_day(m["first_target"])} to
{_day(m["last_target"])}; {m["zero_hours"]:,} zero hours in {m["hours"]:,}), an expanding
training window and a retrain every {m["retrain_every_days"]} days.

- **Against the baselines.** {forecast_verdict(results)}
- **Weather forecasts {"help" if helps else "do not help"}.** The same model without them scores
  F1 {nowx["f1"]:.2f} and Brier {nowx["brier"]:.3f}.
- **It rarely gets a whole day right.** On days with at least one zero hour, the predicted
  set of hours matched exactly on {_pct(model["day_exact_zero_days"])} of them. Whether a day
  has any zero hour at all was called correctly on {_pct(model["day_any"])} of days
  ({_pct(d1["day_any"])} for {BASELINE_NAMES["same_as_d1"]}).
- **It misses the turns.** Of {f["onset"]["days"]} days with zero hours after a week without
  any, it flagged {f["onset"]["model_days_flagged"]}. Its recall on zero hours between 20:00
  and 07:59, mostly windy nights, is {_pct(night["model_recall"])}{night_vs}. The weakest season
  is {weakest[0].lower() + weakest[1:]}, with F1 {seasons[weakest]:.2f}.
- **Tuning the threshold on training data {"paid off" if tuned["f1"] > model["f1"] else "did not pay"}.**
  It moves F1 from {model["f1"]:.2f} to {tuned["f1"]:.2f}.

The full table, the calibration chart, the season breakdown and dated failures are on the
[forecast page]({SITE_URL}/forecast.html) and in the
[forecast notebook]({REPO_URL}/blob/main/notebooks/forecast.ipynb). It is a prototype on one
backtest path, not a trading signal.
"""


def render(df: pd.DataFrame, forecast_results: dict | None = None) -> str:
    """The case study as markdown.

    Needs two complete comparison windows (``findings.WINDOWS``) and raises ``ValueError``
    otherwise, which also fails the site build. ``forecast_results`` defaults to the
    committed backtest results.
    """
    if forecast_results is None:
        forecast_results = forecast.load_results()
    h = findings.headline(df)
    w = h["windows"]
    if w.shape[1] < 2:
        raise ValueError("case study needs data in two comparison windows (see findings.WINDOWS)")
    (n1, a), (n2, b) = list(w.items())[-2:]
    # The text compares annual counts and calls both windows a full seasonal cycle.
    for name in (n1, n2):
        gaps = findings.window_gaps(df, *findings.WINDOWS[name])
        if gaps:
            raise ValueError(f"comparison window {name} is incomplete: " + "; ".join(gaps))
    days = df["date"].nunique()
    calibrated = int(df.groupby("date")["calibrated"].first().sum())
    event_hours = int(df["grid_event"].sum())
    event_days = " and ".join(_day(d) for d in t.GRID_EVENT_DAYS)
    peak_month, peak_hours = h["zero_hours_peak_month"]
    worst_month, worst_rate = h["worst_capture_month"]
    return f"""# Case study: Spanish power prices vs renewables

## Problem

Spain keeps adding solar, and the day-ahead market shows it: midday prices sink while evening
prices hold. I wanted to measure that with public data: how does the price move as renewables
cover more of demand, when do zero and negative prices happen, and how far below the average
price does solar's output clear?

## Data

- **Prices:** OMIE day-ahead marginal price for Spain (`marginalpdbc` daily files), hourly
  until the market moved to 15-minute periods on 1 Oct 2025.
- **Generation and demand:** Red Eléctrica's peninsular real-time feed (5-minute readings)
  and the official daily totals from its REData API.
- **Coverage:** {_day(h["period"][0])} to {_day(h["period"][1])}, {h["hours"]:,} hourly rows
  over {days:,} days. No API token is needed.
- **Licences:** OMIE allows free reuse with the source cited; REE allows informative,
  non-commercial reuse with attribution.

## Method

- **DST-safe hourly prices.** The 15-minute periods are averaged to clock hours with
  timestamps built in UTC, so the 23- and 25-hour days come out right.
- **Calibration to REData.** The real-time feed changed method in December 2025, which
  shifted solar and demand levels overnight. Each day's hourly series is scaled so its daily
  total matches the official REData figure; {calibrated:,} of {days:,} days are calibrated.
- **Capture rate.** Capture price = Σ(price × generation) / Σ(generation), and capture rate =
  capture price / simple average (baseload) price. These are generation-weighted hourly
  capture prices (an estimate): since the market moved to 15-minute periods, price and
  output moves within an hour are averaged away.
- **Blackout exclusion.** The afternoon of {event_days} (the Iberian blackout,
  {event_hours} hours) is left out of every share calculation because measured demand
  collapsed. Its prices stay in, since they were set the day before.

## Findings

Two Oct–Sep windows, so both cover a full seasonal cycle: {n1} and {n2}.

- **Prices fall as renewables rise.** Hourly price and renewables share correlate at
  {h["corr_price_renewables"]:.2f}. Below a 40% share the average price is
  {h["price_share_lt40"]:.1f} EUR/MWh; at 80% or more it is {h["price_share_ge80"]:.1f}.
- **Zero-price hours cluster at midday.** Hours at or below 0 EUR/MWh
  {_moved(a["zero_or_negative_hours"], b["zero_or_negative_hours"], ",.0f")}
  ({a["pct_zero_or_negative"]:.1%} and {b["pct_zero_or_negative"]:.1%} of hours), and
  {h["zero_hours_midday_share"]:.0%} of all of them fell between 10:00 and 17:59. The peak
  month was {_month(peak_month)} with {peak_hours:,}. The lowest hourly price was
  {h["min_price"]:.0f} EUR/MWh.
- **Solar cannibalises its own price.** Solar's share of demand
  {_moved(a["solar_share"], b["solar_share"], ".1%")} and its capture rate
  {_moved(a["solar_capture_rate"], b["solar_capture_rate"], ".0%")}
  ({a["solar_capture"]:.1f} and {b["solar_capture"]:.1f} EUR/MWh against a baseload of
  {a["avg_price"]:.1f} and {b["avg_price"]:.1f}). In the worst complete month,
  {_month(worst_month)}, solar captured {worst_rate:.0%} of baseload.
- **The duck curve.** The average 11:00–16:59 price
  {_moved(a["midday_11_16"], b["midday_11_16"], ".1f")} EUR/MWh, while the 19:00–22:59
  price {_moved(a["evening_19_22"], b["evening_19_22"], ".1f")}.

{forecast_section(forecast_results)}
## Engineering choices

- A pure-Python pipeline (pandas): no database, no API token, a GitHub Actions cron.
- A per-day parquet cache, so a refresh only fetches new days, and a committed hourly table,
  so everything runs on clone.
- One set of Plotly figure builders shared by the Streamlit app, the notebook and the static
  site.
- A deterministic static build: the same data gives a byte-identical site, with no CDN.
- Offline tests with recorded fixtures of the real OMIE and REE responses.

## Tests and CI

An offline pytest suite in `tests/` runs in CI on every push to `main` and every pull
request, with ruff lint and format checks. CI also builds the static site, checks that this
text matches its generator, and checks with Node that the page's JavaScript KPIs equal the
Python ones.

## What I'd do next

- A toll-aware retail estimate (what a zero-price hour means on a 2.0TD or 3.0TD bill),
  started in the [companion repo]({COMPANION_URL}).
- For the D+2 forecast: point-in-time REE data instead of today's revised values, the
  15-minute prices as the target, and a live daily run scored against the backtest.
- Intraday and balancing prices, which this day-ahead view leaves out.
- Portugal, whose price is already in the OMIE files.
"""


def for_readme(md: str) -> str:
    """Demote every heading one level so the case study sits under the README's own title."""
    return re.sub(r"^(#+ )", r"#\1", md.strip(), flags=re.MULTILINE)


def update_readme(readme: str, md: str) -> str:
    """Replace the text between the case-study markers with ``md`` (headings demoted)."""
    if readme.count(START) != 1 or readme.count(END) != 1 or readme.index(START) > readme.index(END):
        raise ValueError(f"README needs exactly one {START} ... {END} block")
    head, rest = readme.split(START)
    tail = rest.split(END)[1]
    return f"{head}{START}\n{for_readme(md)}\n{END}{tail}"
