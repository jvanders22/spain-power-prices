# Case study: Spanish power prices vs renewables

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
- **Capture rate.** Capture price = Σ(price × generation) / Σ(generation), and capture rate =
  capture price / simple average (baseload) price. These are generation-weighted hourly
  capture prices (an estimate): since the market moved to 15-minute periods, price and
  output moves within an hour are averaged away.
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

## D+2 forecast of zero-price hours

A prototype forecasts, at 13:00 on day D, the probability that each hour of day D+2 clears at
or below 0 EUR/MWh. It is a gradient-boosted tree model on prices through D+1, REE generation
and demand through D-1, the calendar of D+2 and weather forecasts issued 72 hours ahead
(Open-Meteo), with every input cut at what was already published. The backtest is
rolling-origin: one forecast per day for 641 days (6 Jan 2025 to
8 Oct 2026; 1,708 zero hours in 15,383), an expanding
training window and a retrain every 7 days.

- **Against the baselines.** The model beats all three baselines on this backtest: F1 for zero hours is 0.77 against 0.67 for the best baseline ("same as D+1"), and the Brier score is 0.038 against 0.069 (climatology; lower is better).
- **Weather forecasts help.** The same model without them scores
  F1 0.72 and Brier 0.044.
- **It rarely gets a whole day right.** On days with at least one zero hour, the predicted
  set of hours matched exactly on 15% of them. Whether a day
  has any zero hour at all was called correctly on 87% of days
  (80% for "same as D+1").
- **It misses the turns.** Of 12 days with zero hours after a week without
  any, it flagged 1. Its recall on zero hours between 20:00
  and 07:59, mostly windy nights, is 31%, below the 51% of "same as D+1". The weakest season
  is autumn (Sep–Nov), with F1 0.55.
- **Tuning the threshold on training data did not pay.**
  It moves F1 from 0.77 to 0.74.

The full table, the calibration chart, the season breakdown and dated failures are on the
[forecast page](https://jvanders22.github.io/spain-power-prices/forecast.html) and in the
[forecast notebook](https://github.com/jvanders22/spain-power-prices/blob/main/notebooks/forecast.ipynb). It is a prototype on one
backtest path, not a trading signal.

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
- For the D+2 forecast: point-in-time REE data instead of today's revised values, the
  15-minute prices as the target, and a live daily run scored against the backtest.
- Intraday and balancing prices, which this day-ahead view leaves out.
- Portugal, whose price is already in the OMIE files.
