# Case study: Spanish power prices vs renewables

## Problem

Spain keeps adding solar, and the day-ahead market shows it: midday prices sink while evening
prices hold. I wanted to measure that with public data: how does the price move as renewables
cover more of demand, when do zero and negative prices happen, and how far below the average
price does solar actually sell?

## Data

- **Prices:** OMIE day-ahead marginal price for Spain (`marginalpdbc` daily files), hourly
  until the market moved to 15-minute periods on 1 Oct 2025.
- **Generation and demand:** Red Eléctrica's peninsular real-time feed (5-minute readings)
  and the official daily totals from its REData API.
- **Coverage:** 1 Oct 2024 to 9 Oct 2026, 17,735 hourly rows
  over 739 days. No API token is needed.
- **Licences:** OMIE allows free reuse with the source cited; REE allows informative,
  non-commercial reuse with attribution.

## Method

- **DST-safe hourly prices.** The 15-minute periods are averaged to clock hours with
  timestamps built in UTC, so the 23- and 25-hour days come out right.
- **Calibration to REData.** The real-time feed changed method in December 2025, which
  shifted solar and demand levels overnight. Each day's hourly series is scaled so its daily
  total matches the official REData figure; 738 of 739 days are calibrated.
- **Capture rate.** Capture price = Σ(price × generation) / Σ(generation). Capture rate =
  capture price / simple average (baseload) price.
- **Blackout exclusion.** The afternoon of 28 Apr 2025 (the Iberian blackout,
  12 hours) is left out of every share calculation because measured demand
  collapsed. Its prices stay in, since they were set the day before.

## Findings

Two Oct–Sep windows, so both cover a full seasonal cycle: Oct 2024–Sep 2025 and Oct 2025–Sep 2026.

- **Prices fall as renewables rise.** Hourly price and renewables share correlate at
  -0.72. Below a 40% share the average price is
  133.6 EUR/MWh; at 80% or more it is 12.9.
- **Zero-price hours cluster at midday.** Hours at or below 0 EUR/MWh
  rose from 775 to 944
  (8.8% and 10.8% of hours), and
  91% of all of them fell between 10:00 and 17:59. The peak
  month was May 2025 with 269. The lowest hourly price was
  -15 EUR/MWh.
- **Solar cannibalises its own price.** Solar's share of demand
  rose from 21.5% to 24.9% and its capture rate
  fell from 56% to 53%
  (40.1 and 38.9 EUR/MWh against a baseload of
  71.3 and 73.3). In the worst complete month,
  May 2025, solar captured 17% of baseload.
- **The duck curve.** The average 11:00–16:59 price
  fell from 38.9 to 25.3 EUR/MWh, while the 19:00–22:59
  price rose from 106.5 to 115.3.

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
  started in the [companion repo](https://github.com/jvanders22/spain-negative-price-alert).
- A D+2 forecast of zero-price hours, with a backtest.
- Intraday and balancing prices, which this day-ahead view leaves out.
- Portugal, whose price is already in the OMIE files.
