# Spanish power prices vs renewables

Interactive analysis of the Spanish day-ahead electricity market against the peninsular
generation mix, Oct 2024 to Oct 2026, built on public data with no API token.

It answers three questions, and adds a prototype D+2 forecast of zero-price hours with a backtest:

1. How does the day-ahead price move as renewables cover more of demand?
2. When do zero and negative prices happen, by month and hour?
3. **Solar cannibalisation:** how far below the average price does solar's output clear, and is the gap widening?

**Live dashboard:** <https://jvanders22.github.io/spain-power-prices/> (after Pages is enabled).
It is a static build of the dashboard below, so it loads instantly and never sleeps.

![Dashboard](docs/img/dashboard.png)

## Key findings

Hourly data from 1 Oct 2024 to 9 Oct 2026 (17,735 hours). The two comparison windows are
Oct–Sep years, so both cover a full seasonal cycle. All numbers are computed in
[`notebooks/analysis.ipynb`](notebooks/analysis.ipynb) via `spain_power.findings`.

| | Oct 2024–Sep 2025 | Oct 2025–Sep 2026 |
|---|---:|---:|
| Average day-ahead price (EUR/MWh) | 71.3 | 73.3 |
| Hours at or below 0 EUR/MWh | 775 (8.8%) | 944 (10.8%) |
| …of which strictly negative | 540 | 768 |
| Renewables share of demand | 59.6% | 61.1% |
| Solar share of demand | 21.5% | 24.9% |
| Solar capture price (EUR/MWh) | 40.1 | 38.9 |
| Solar capture rate (vs baseload) | 56% | 53% |
| Avg price 11:00–16:59 vs 19:00–22:59 (EUR/MWh) | 38.9 vs 106.5 | 25.3 vs 115.3 |

1. **Prices fall as renewables cover more of demand.** Hourly price and renewables share correlate at
   **−0.72**. When renewables cover under 40% of demand, the average price is
   **133.6 EUR/MWh**. At 80% or more it falls to **12.9 EUR/MWh**, with a median of
   2.6.
2. **Zero-price hours are growing, and they cluster at midday in spring.** 1,728 hours
   (9.7%) cleared at or below zero, and **91%** of them fell between 10:00 and 17:59. The
   peak was May 2025, with 269 such hours. Negative prices stay shallow: the lowest hourly
   average was −15 EUR/MWh.
3. **Solar is cannibalising its own price.** Solar's capture price was **53%** of baseload
   in the latest year, down from 56%, while its share of demand rose from 21.5% to 24.9%.
   In the worst month (May 2025) solar captured only **17%** of baseload.
4. **The duck curve is deepening.** Average midday prices fell from 38.9 to 25.3 EUR/MWh,
   while evening prices rose from 106.5 to 115.3. That widening spread is the revenue
   opportunity for batteries and flexible demand.
5. **Wind behaves differently.** Wind's capture price tracks baseload closely because wind
   output is spread across the day. February 2026 shows the wind case: overnight prices
   averaged 5.7 EUR/MWh with wind covering 38% of night-time demand, against 98.8 EUR/MWh
   and 25% a year earlier.

<table>
<tr><td><img src="docs/img/price_vs_renewables.png" alt="Price vs renewables share"></td>
<td><img src="docs/img/negative_hours_heatmap.png" alt="Zero/negative price hours heatmap"></td></tr>
<tr><td><img src="docs/img/capture_prices.png" alt="Baseload vs solar and wind capture price"></td>
<td><img src="docs/img/hourly_profile.png" alt="Average price by hour of day"></td></tr>
</table>

### Wholesale is not your bill

Everything here is the OMIE day-ahead price: the wholesale price of energy at the busbar. A
2.0TD household or small-business bill adds losses and system services, peajes (CNMC) and cargos
(MITECO) by time-of-use period, the electricity tax and VAT, plus a fixed power term. The static
site's [`wholesale-vs-bill.html`](https://jvanders22.github.io/spain-power-prices/wholesale-vs-bill.html)
page (source: `src/spain_power/site.py`, calendar and 2026 terms in `src/spain_power/tariff20td.py`)
sets the 2026 regulated energy terms beside the hourly prices as an illustration. The full
2.0TD/3.0TD calculator is in the companion repo,
[spain-negative-price-alert](https://github.com/jvanders22/spain-negative-price-alert/blob/main/docs/tariffs.md).

### D+2 forecast of zero-price hours (prototype)

`src/spain_power/forecast.py` forecasts, at about 13:00 Europe/Madrid on day D, the probability
that each hour of delivery day D+2 clears at or below 0 EUR/MWh, and backtests it against three
baselines. The results, including where it fails, are in the case study below (generated from
[`docs/forecast_results.json`](docs/forecast_results.json)), on the site's
[`forecast.html`](https://jvanders22.github.io/spain-power-prices/forecast.html) page and in
[`notebooks/forecast.ipynb`](notebooks/forecast.ipynb).

- **Information cut-off** (`forecast.available_at`). Prices through the end of D+1, since the
  day-ahead result for D+1 is published around 13:00 on D. REE generation and demand through the
  end of D-1 only, because the real-time feed for D is half a day short at 13:00. The calendar of
  D+2. Features are computed from inputs already cut at those limits, and the tests scramble
  everything after them and check that no feature moves.
- **Weather.** Archived *forecasts* from Open-Meteo's Previous Runs API at six points (Seville,
  Badajoz, Ciudad Real, Zaragoza, Burgos, A Coruña), using only the `_previous_day3` fields: the
  value predicted 72 hours before each hour, so 23:00 on D-1 at the latest. The `_previous_day2`
  fields would come from runs started after 13:00 on D for every afternoon hour of D+2, so they
  are not used. Observed or reanalysis weather is never a feature. The archive covers the whole
  history, so there is one backtest period. Raw responses are cached in `data/weather/`.
- **Model.** Gradient-boosted trees (scikit-learn `HistGradientBoostingClassifier`, fixed seed):
  the signal is in thresholds and interactions (hour × season × radiation × yesterday's price),
  missing values need no handling, and a fit takes about a second. The settings were fixed
  before the backtest and not tuned on it.
- **Backtest.** Rolling origin, one forecast per day, expanding training window, at least 90
  training days. Retraining is weekly rather than monthly because the zero-hour season turns
  within weeks. The F1-maximising threshold is chosen on the last quarter of each training
  window, never on the days being scored.
- **Target.** Hourly prices, which since 1 Oct 2025 are the mean of four 15-minute prices. A
  quarter-hour at or below zero inside an hour with a positive mean is not counted.
- **Caveat.** The REE inputs are today's values, calibrated to daily totals that REE revises
  for weeks, not the values visible on day D.

The backtest is a manual step and CI never runs it or touches the network:

```bash
python scripts/backtest_forecast.py     # ~10 min; writes docs/forecast_results.json and
                                        # data/processed/forecast_backtest.parquet
python scripts/build_case_study.py      # refresh the generated text
python scripts/build_site.py
```

The site and the case study read the committed results file, so they show the backtest as of
its own "data through" date until the script is run again.

<!-- case-study:start -->
## Case study: Spanish power prices vs renewables

### Problem

Spain keeps adding solar, and the day-ahead market shows it: midday prices sink while evening
prices hold. I wanted to measure that with public data: how does the price move as renewables
cover more of demand, when do zero and negative prices happen, and how far below the average
price does solar's output clear?

### Data

- **Prices:** OMIE day-ahead marginal price for Spain (`marginalpdbc` daily files), hourly
  until the market moved to 15-minute periods on 1 Oct 2025.
- **Generation and demand:** Red Eléctrica's peninsular real-time feed (5-minute readings)
  and the official daily totals from its REData API.
- **Coverage:** 1 Oct 2024 to 9 Oct 2026, 17,735 hourly rows
  over 739 days. No API token is needed.
- **Licences:** OMIE allows free reuse with the source cited; REE allows informative,
  non-commercial reuse with attribution.

### Method

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

### Findings

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

### D+2 forecast of zero-price hours

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

### Engineering choices

- A pure-Python pipeline (pandas): no database, no API token, a GitHub Actions cron.
- A per-day parquet cache, so a refresh only fetches new days, and a committed hourly table,
  so everything runs on clone.
- One set of Plotly figure builders shared by the Streamlit app, the notebook and the static
  site.
- A deterministic static build: the same data gives a byte-identical site, with no CDN.
- Offline tests with recorded fixtures of the real OMIE and REE responses.

### Tests and CI

An offline pytest suite in `tests/` runs in CI on every push to `main` and every pull
request, with ruff lint and format checks. CI also builds the static site, checks that this
text matches its generator, and checks with Node that the page's JavaScript KPIs equal the
Python ones.

### What I'd do next

- A toll-aware retail estimate (what a zero-price hour means on a 2.0TD or 3.0TD bill),
  started in the [companion repo](https://github.com/jvanders22/spain-negative-price-alert).
- For the D+2 forecast: point-in-time REE data instead of today's revised values, the
  15-minute prices as the target, and a live daily run scored against the backtest.
- Intraday and balancing prices, which this day-ahead view leaves out.
- Portugal, whose price is already in the OMIE files.
<!-- case-study:end -->

## What's in the repo

```
app/streamlit_app.py        interactive dashboard (date filter, threshold, KPIs, 4 tabs, CSV export)
notebooks/analysis.ipynb    the analysis, executed, with static charts that render on GitHub
notebooks/forecast.ipynb    the D+2 forecast backtest: tables, calibration, failures (executed)
src/spain_power/
  omie.py                   OMIE day-ahead price files: parse, 15-min -> hourly, DST-safe
  ree.py                    REE real-time generation mix + REData daily totals
  esios.py                  optional ESIOS client (needs ESIOS_TOKEN; not used by default)
  cache.py                  per-day parquet cache in data/raw, combined table in data/processed
  transform.py              join, calibration, renewables share, capture prices, KPIs
  charts.py                 plotly figures shared by the app, notebook, static site and README images
  findings.py               headline numbers used in this README
  case_study.py             case-study text, generated from findings
  tariff20td.py             2.0TD periods, holidays and 2026 peajes + cargos
  forecast.py               D+2 zero-hour forecast: cut-off, features, baselines, metrics, backtest
  weather.py                Open-Meteo previous-runs client (72-hour-ahead forecasts) + JSON cache
  site.py                   static site builder (pages, embedded data, figure specs)
  static/app.js             the static dashboard's filters, KPIs and charts (plain JS + plotly.js)
scripts/
  refresh.py                incremental daily refresh (+ rebuild of hourly.parquet)
  build_site.py             static site -> _site/ (dashboard, case study, wholesale-vs-bill, forecast)
  backtest_forecast.py      D+2 forecast backtest -> docs/forecast_results.json (manual, ~10 min)
  build_case_study.py       docs/case_study.md + the README case-study section (--check in CI)
  render_figures.py         README chart PNGs (kaleido)
  screenshot_app.py         dashboard screenshot (playwright)
  build_notebook.py         regenerates the notebook source
  build_forecast_notebook.py  regenerates the forecast notebook source
  export_video_data.py      numbers for the explainer video
tests/                      offline pytest tests using recorded fixtures
docs/case_study.md          the case study (generated)
docs/forecast_results.json  backtest metrics read by the site, case study and notebook (generated)
video/                      Remotion explainer video
data/processed/hourly.parquet   the hourly dataset (committed so the app runs on clone)
data/processed/forecast_backtest.parquet   one row per forecast hour of the backtest
data/weather/               cached Open-Meteo responses (weather forecasts, CC BY 4.0)
.github/workflows/          ci.yml (lint, tests, site build), refresh.yml (daily data), pages.yml (deploy)
```

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

streamlit run app/streamlit_app.py      # dashboard on http://localhost:8501
python scripts/refresh.py               # pull new days (first run without data/raw: ~10 min)
python scripts/build_site.py            # static site in _site/ (python -m http.server -d _site)
python scripts/build_case_study.py      # regenerate docs/case_study.md and the README section
python scripts/backtest_forecast.py     # rerun the D+2 forecast backtest (manual, ~10 min)
pytest -q && ruff check .
jupyter nbconvert --to notebook --execute --inplace notebooks/analysis.ipynb
jupyter nbconvert --to notebook --execute --inplace notebooks/forecast.ipynb
```

`refresh.py` defaults to the last 24 months. Use `--start` / `--end` for other ranges.

CI (`.github/workflows/ci.yml`) runs lint and tests on pushes to `main` and on pull requests,
checks that the case study matches its generator, builds the static site and uploads it as the
`static-site` artifact. `.github/workflows/pages.yml` builds the same site and deploys it to
GitHub Pages once the repository variable `PAGES_ENABLED=true` is set (Pages on the Free plan
needs a public repo). The build is deterministic and has no CDN or other external requests:
plotly.js is copied from the installed plotly package.
`.github/workflows/refresh.yml` runs the refresh and tests daily at 14:30 UTC, after OMIE
publishes next-day prices, and uploads the new table as an artifact. To have it commit the
table back to the repo, set the repository variable `COMMIT_DATA=true`.

## Data sources and method

| Data | Source | Token | Resolution |
|---|---|---|---|
| Day-ahead marginal price, Spain | [OMIE](https://www.omie.es) `marginalpdbc` daily files | none | hourly; 15-min from 1 Oct 2025 |
| Demand and generation by technology, peninsular | REE real-time demand viewer feed ([demanda.ree.es](https://demanda.ree.es)) | none | 5-min |
| Official daily generation and demand, peninsular | [REE REData API](https://www.ree.es/en/datos/apidata) (`apidatos.ree.es`) | none | daily |
| (optional) ESIOS indicators | [ESIOS](https://www.esios.ree.es) | `ESIOS_TOKEN` | — |
| Weather forecasts issued 72 h ahead, six points (forecast only) | [Open-Meteo](https://open-meteo.com) Previous Runs API | none | hourly |

Method notes:

- **Prices.** OMIE moved the day-ahead market to 15-minute periods on 1 Oct 2025. Those
  periods are averaged to clock hours, with timestamps built in UTC so the 23- and 25-hour
  DST days are handled correctly. When a day's `.1` file has been replaced by a corrected
  version, the loader falls back to `.2`, `.3` and so on.
- **Why not REData for hourly generation?** The REData generation-structure endpoint only
  serves daily data. The hourly shape therefore comes from REE's real-time feed (5-min
  readings averaged to hours; the repeated DST hour is labelled `2A`/`2B` and handled).
- **Calibration.** The real-time feed changed method on **11 Dec 2025**. Solar PV jumped by
  about 23% overnight relative to REData, and demand by about 3%. To keep the series
  consistent, each day's hourly wind, solar, hydro and demand values are scaled so their
  daily totals match REE's official REData figures. Only complete days (all 23/24/25 clock
  hours present, with a REData total for every series) are scaled, and scaling runs before
  prices are joined. The `*_rt` columns keep the raw values, and the `calibrated` column
  flags which days were scaled; in the current data that is every day except the partial
  current day.
- **Renewables share** = (wind + solar PV + solar thermal + hydro) / peninsular demand.
  Hydro is reported net of pumped-storage consumption, so it is clipped at zero. The share
  can exceed 100% when Spain is exporting or pumping.
- **Capture price** = Σ(price × generation) / Σ(generation). **Capture rate** = capture
  price / simple average (baseload) price. These are generation-weighted hourly capture
  prices (an estimate). Since the move to 15-minute prices they are an hourly proxy, because
  within-hour co-movement of price and output is averaged away.
- **Iberian blackout, 28 Apr 2025 from 12:33.** That day's prices are kept, because they
  were set the day before. Its afternoon hours are excluded from renewables-share
  calculations, including the aggregate shares in the table above, because measured
  demand collapsed to near zero.

**Limitations.** The analysis covers the day-ahead market only, with no intraday,
balancing or capacity revenues. REE's real-time values are provisional. The Balearic and
Canary systems are excluded.

### Licences and attribution

- **OMIE:** public, free information that may be used freely if its original content is
  respected, with the source cited ([legal notice](https://www.omie.es/en/legal-warning)).
  *Source: OMIE, Mercado diario, precio marginal (marginalpdbc).*
- **Red Eléctrica (REE):** reuse citing REE as the source is permitted for informative,
  non-commercial purposes; commercial use needs REE's prior written authorisation
  ([aviso legal](https://www.ree.es/es/aviso-legal)). *Source: Red Eléctrica, REData and
  demand monitoring.*
- **Open-Meteo:** weather forecast data by [Open-Meteo.com](https://open-meteo.com/), licensed
  under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The free API is for
  non-commercial use ([terms](https://open-meteo.com/en/terms)); the cached responses in
  `data/weather/` are redistributed under the same licence, unmodified.
- This project is not affiliated with OMIE, Red Eléctrica or Open-Meteo. The code is MIT-licensed (see
  [LICENSE](LICENSE)). The licence does not cover the third-party data.

## Video explainer

A 26.5-second animated explainer of the solar findings (Remotion, 1080×1080) lives in [`video/`](video/README.md). Numbers are exported from the processed data by `scripts/export_video_data.py`.
