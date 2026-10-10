"""Case study text, generated from the hourly table.

One source for three places: ``docs/case_study.md``, the README section between the
``case-study`` markers and the static site's case-study page. Every number comes from
:mod:`spain_power.findings` or :mod:`spain_power.transform` at generation time.
"""

from __future__ import annotations

import re

import pandas as pd

from . import findings
from . import transform as t

START = "<!-- case-study:start -->"
END = "<!-- case-study:end -->"
COMPANION_URL = "https://github.com/jvanders22/spain-negative-price-alert"


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


def render(df: pd.DataFrame) -> str:
    """The case study as markdown.

    Needs two complete comparison windows (``findings.WINDOWS``) and raises ``ValueError``
    otherwise, which also fails the site build.
    """
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
- A D+2 forecast of zero-price hours, with a backtest.
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
