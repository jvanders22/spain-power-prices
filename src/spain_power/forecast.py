"""D+2 forecast of zero-price hours, with baselines, metrics and a rolling-origin backtest.

For each local clock hour of delivery day D+2 the model gives P(OMIE price <= 0), using only
what is known at about 13:00 Europe/Madrid on day D (see :func:`available_at`):

- OMIE day-ahead prices up to the end of D+1: the result for D+1 is published around 13:00 on
  D, and OMIE does not revise published day-ahead prices;
- weather forecasts issued 72 hours before each target hour (:mod:`spain_power.weather`),
  taken from Open-Meteo's archive of past runs, never observed weather;
- the calendar of D+2.

:func:`build_features` first cuts every input at those limits (:func:`select_inputs`) and
computes features from the cut frames only, so nothing later can reach a feature.

The target is defined on hourly prices. Since 1 Oct 2025 those are means of four 15-minute
prices, so a quarter-hour at or below zero inside an hour with a positive mean is not counted.

REE generation and demand are deliberately not used. The hourly table holds today's version
of the REE data (calibrated to REData daily totals, which REE revises for some weeks), and the
version visible at 13:00 on D is not archived, so any REE feature would leak later revisions.
The REE columns may still describe example days after the fact (:func:`failure_analysis`), as
realised values, never as model inputs.

Daylight-saving folds: a repeated local hour (02:00 on the last Sunday of October) counts as a
zero hour-of-day if any of its delivery hours was at or below zero; daily zero-hour counts sum
the original delivery hours; price-level features average the repeated hour. Both target rows
of a repeated hour get the same features and calls. A skipped hour (spring) is missing: its
price features are NaN and the baselines call it "not zero".
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import tariff20td, weather
from .transform import TZ, expected_hours

RESULTS = Path(__file__).resolve().parents[2] / "docs" / "forecast_results.json"
BACKTEST = Path(__file__).resolve().parents[2] / "data" / "processed" / "forecast_backtest.parquet"

HORIZON_DAYS = 2
MIN_TRAIN_DAYS = 90
RETRAIN_EVERY_DAYS = 7
SEED = 0
HISTORY_DAYS = 28  # longest look-back of any feature, in days before the target day

CALENDAR = ["hour", "dow", "is_weekend", "is_holiday", "doy_sin", "doy_cos"]
PRICE = [
    "p_d1",
    "p_d2",
    "p_d3",
    "p_d7",
    "d1_zero_hours",
    "d1_min",
    "d1_mean",
    "d1_midday",
    "d2_zero_hours",
    "zshare7_h",
    "zshare28_h",
    "zero_hours_7d",
    "days_since_zero",
]
WEATHER = [
    "wx_rad",
    "wx_wind",
    "wx_wind3",
    "wx_temp",
    "wx_rad_day",
    "wx_wind_day",
    "wx_temp_day",
    "wx_rad_d1",
    "wx_wind_d1",
    "wx_rad_day_d1",
    "wx_wind_day_d1",
]
FEATURES = CALENDAR + PRICE + WEATHER
FEATURES_NO_WEATHER = CALENDAR + PRICE
_WX_COLS = ["wx_rad", "wx_wind", "wx_wind3", "wx_temp"]

SEASONS = {
    "Winter (Dec–Feb)": (12, 1, 2),
    "Spring (Mar–May)": (3, 4, 5),
    "Summer (Jun–Aug)": (6, 7, 8),
    "Autumn (Sep–Nov)": (9, 10, 11),
}
HOUR_GROUPS = {
    "Night (20:00–07:59)": (20, 21, 22, 23, 0, 1, 2, 3, 4, 5, 6, 7),
    "Shoulder (08:00–09:59, 18:00–19:59)": (8, 9, 18, 19),
    "Midday (10:00–17:59)": (10, 11, 12, 13, 14, 15, 16, 17),
}
# method key -> (label, prediction column, probability column)
METHODS = {
    "model": ("Model, p ≥ 0.5", "pred_model", "p_model"),
    "model_tuned": ("Model, threshold tuned on training data", "pred_model_tuned", "p_model"),
    "model_no_weather": ("Model without weather, p ≥ 0.5", "pred_nowx", "p_nowx"),
    "same_as_d1": ("Baseline: same as D+1", "base_d1", "base_d1"),
    "last_week": ("Baseline: same hour last week", "base_week", "base_week"),
    "climatology": ("Baseline: climatology (month × hour)", "pred_clim", "p_clim"),
}
BASELINES = ["same_as_d1", "last_week", "climatology"]


# ---- cut-off ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Cutoff:
    """What is known at about 13:00 Europe/Madrid on ``origin``. Limits are exclusive."""

    origin: dt.date
    target: dt.date
    prices_before: pd.Timestamp
    weather_before: pd.Timestamp
    weather_lead: str


def _midnight(day: dt.date) -> pd.Timestamp:
    return pd.Timestamp(day).tz_localize(TZ)


def available_at(origin: dt.date) -> Cutoff:
    """The information cut-off for a forecast made on day ``origin`` (D) for D+2.

    - Prices: everything delivered before 00:00 on D+2, i.e. through the end of D+1.
    - Weather: forecasts for hours before 00:00 on D+3 (the target day and earlier), and only
      the ``previous_day3`` fields, issued 72 hours before each hour.
    """
    day = dt.timedelta(days=1)
    return Cutoff(
        origin=origin,
        target=origin + HORIZON_DAYS * day,
        prices_before=_midnight(origin + 2 * day),
        weather_before=_midnight(origin + 3 * day),
        weather_lead=weather.LEAD,
    )


@dataclass(frozen=True)
class Inputs:
    cutoff: Cutoff
    prices: pd.DataFrame
    weather: pd.DataFrame | None


def _local(frame: pd.DataFrame) -> pd.DataFrame:
    local = frame["ts_utc"].dt.tz_convert(TZ)
    return frame.assign(date=local.dt.strftime("%Y-%m-%d"), hour=local.dt.hour)


def select_inputs(hourly: pd.DataFrame, wx: pd.DataFrame | None, origin: dt.date) -> Inputs:
    """Cut ``hourly`` and the aggregated weather ``wx`` at :func:`available_at` ``(origin)``.

    Every feature is computed from the returned frames only. No REE column is returned.
    """
    cut = available_at(origin)
    since = _midnight(cut.target - dt.timedelta(days=HISTORY_DAYS))
    ts = hourly["ts_utc"]
    prices = hourly.loc[(ts >= since) & (ts < cut.prices_before), ["ts_utc", "price_es"]]
    wxc = None
    if wx is not None:
        bad = [c for c in wx.columns if c != "ts_utc" and c not in _WX_COLS]
        if bad:
            raise ValueError(f"unexpected weather columns: {bad}")
        wxc = _local(wx.loc[(wx["ts_utc"] >= since) & (wx["ts_utc"] < cut.weather_before)])
    return Inputs(cut, _local(prices), wxc)


# ---- features --------------------------------------------------------------------------


def target_hours(target: dt.date) -> pd.DataFrame:
    """The clock hours of a local calendar day (23, 24 or 25 rows), from the calendar alone."""
    ts = pd.date_range(
        _midnight(target), _midnight(target + dt.timedelta(days=1)), freq="h", inclusive="left"
    )
    return pd.DataFrame({"ts_utc": ts.tz_convert("UTC"), "date": f"{target:%Y-%m-%d}", "hour": ts.hour})


def _matrix(frame: pd.DataFrame, col: str, days: list[str]) -> pd.DataFrame:
    """Day x hour-of-day table of ``col`` (a repeated DST hour is averaged, a skipped one NaN)."""
    m = frame.groupby(["date", "hour"])[col].mean().unstack("hour")
    return m.reindex(index=days, columns=range(24)).astype("float64")


def _zero_matrix(frame: pd.DataFrame, days: list[str]) -> pd.DataFrame:
    """Day x hour-of-day zero indicator from the original delivery hours.

    A repeated DST hour is zero if any of its delivery hours was at or below zero; a skipped
    or missing hour is NaN.
    """
    z = frame.assign(z=(frame["price_es"] <= 0).astype("float64"))
    m = z.groupby(["date", "hour"])["z"].max().unstack("hour")
    return m.reindex(index=days, columns=range(24)).astype("float64")


def _daily_zero_hours(frame: pd.DataFrame, days: list[str]) -> pd.Series:
    """Zero delivery hours per day, summed over the original rows (a fold counts twice); NaN
    for a day without prices."""
    z = (frame["price_es"] <= 0).astype("float64")
    return z.groupby(frame["date"]).sum().reindex(days)


def _mean(values) -> float:
    """Mean of the finite values, NaN if there are none."""
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    return float(v.mean()) if len(v) else np.nan


def build_features(hourly: pd.DataFrame, wx: pd.DataFrame | None, origin: dt.date) -> pd.DataFrame:
    """One row per clock hour of ``origin + 2`` with every feature and the two price baselines.

    ``wx`` is ``weather.aggregate`` output or ``None`` (weather columns are then NaN).
    The target is not attached here; see :func:`attach_target`.
    """
    inp = select_inputs(hourly, wx, origin)
    target = inp.cutoff.target
    out = target_hours(target)
    out.insert(0, "origin", f"{origin:%Y-%m-%d}")
    h = out["hour"].to_numpy()
    days = [f"{target - dt.timedelta(days=k):%Y-%m-%d}" for k in range(HISTORY_DAYS, -1, -1)]

    def back(m: pd.DataFrame, k: int) -> np.ndarray:
        return m.loc[days[-1 - k]].to_numpy()

    # Calendar of the target day.
    doy = target.timetuple().tm_yday
    out["dow"] = target.weekday()
    out["is_weekend"] = int(target.weekday() >= 5)
    out["is_holiday"] = int(tariff20td.is_holiday(target))
    out["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    out["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)

    # Prices through D+1 (= target - 1).
    p = _matrix(inp.prices, "price_es", days)
    zero = _zero_matrix(inp.prices, days)
    for k in (1, 2, 3, 7):
        out[f"p_d{k}"] = back(p, k)[h]
    d1 = back(p, 1)
    daily_zero = _daily_zero_hours(inp.prices, days)
    out["d1_zero_hours"] = daily_zero.iloc[-2]
    out["d1_min"] = np.nanmin(d1) if np.isfinite(d1).any() else np.nan
    out["d1_mean"] = _mean(d1)
    out["d1_midday"] = _mean(d1[10:18])
    out["d2_zero_hours"] = daily_zero.iloc[-3]
    out["zshare7_h"] = zero.iloc[-8:-1].mean().to_numpy()[h]
    out["zshare28_h"] = zero.iloc[:-1].mean().to_numpy()[h]
    out["zero_hours_7d"] = daily_zero.iloc[-8:-1].mean()
    hit = np.flatnonzero(daily_zero.iloc[:-1].to_numpy()[::-1] > 0)
    out["days_since_zero"] = float(hit[0] + 1) if len(hit) else float(HISTORY_DAYS + 1)
    out["base_d1"] = back(zero, 1)[h] == 1
    out["base_week"] = back(zero, 7)[h] == 1

    # Weather forecasts for the target day and the day before, both issued 72 hours ahead.
    if inp.weather is None:
        for c in WEATHER:
            out[c] = np.nan
    else:
        w = {c: _matrix(inp.weather, c, days) for c in _WX_COLS}
        for c in _WX_COLS:
            out[c] = back(w[c], 0)[h]
        for name in ("rad", "wind", "temp"):
            out[f"wx_{name}_day"] = _mean(back(w[f"wx_{name}"], 0))
        for name in ("rad", "wind"):
            out[f"wx_{name}_d1"] = back(w[f"wx_{name}"], 1)[h]
            out[f"wx_{name}_day_d1"] = _mean(back(w[f"wx_{name}"], 1))
    return out


def attach_target(rows: pd.DataFrame, hourly: pd.DataFrame) -> pd.DataFrame:
    """Add the realised ``price`` and ``y`` (price <= 0); hours without a price are dropped."""
    actual = hourly[["ts_utc", "price_es"]].rename(columns={"price_es": "price"})
    out = rows.merge(actual, on="ts_utc", how="inner")
    out["y"] = out["price"] <= 0
    return out


def complete_days(hourly: pd.DataFrame) -> list[str]:
    """Local days of the table that hold every clock hour."""
    counts = hourly.groupby("date").size()
    return [d for d, n in counts.items() if n == expected_hours(d)]


def feature_table(hourly: pd.DataFrame, wx: pd.DataFrame | None) -> pd.DataFrame:
    """Features and targets for every complete target day with a full week of price history."""
    days = complete_days(hourly)
    first = dt.date.fromisoformat(hourly["date"].min()) + dt.timedelta(days=7)
    frames = []
    for d in days:
        target = dt.date.fromisoformat(d)
        if target >= first:
            frames.append(build_features(hourly, wx, target - dt.timedelta(days=HORIZON_DAYS)))
    return attach_target(pd.concat(frames, ignore_index=True), hourly)


# ---- baselines and model ---------------------------------------------------------------


def climatology(train: pd.DataFrame) -> dict:
    """Zero-hour frequency per (month, hour) of the training rows, with fallbacks.

    A month the training window has not seen falls back to the hour's frequency over all
    training rows, and an unseen hour to the overall frequency.
    """
    month = pd.to_datetime(train["date"]).dt.month
    y = train["y"].astype(float)
    return {
        "month_hour": y.groupby([month, train["hour"]]).mean().to_dict(),
        "hour": y.groupby(train["hour"]).mean().to_dict(),
        "all": float(y.mean()) if len(y) else 0.0,
    }


def predict_climatology(table: dict, rows: pd.DataFrame) -> np.ndarray:
    month = pd.to_datetime(rows["date"]).dt.month
    return np.array(
        [
            table["month_hour"].get((m, h), table["hour"].get(h, table["all"]))
            for m, h in zip(month, rows["hour"], strict=True)
        ],
        dtype=float,
    )


THRESHOLDS = np.round(np.arange(0.05, 0.951, 0.01), 2)


def best_f1_threshold(y, p) -> float:
    """The threshold in 0.05..0.95 with the highest F1; ties go to the one nearest 0.5.

    Returns 0.5 when there are no positives or no threshold predicts a true positive.
    """
    y = np.asarray(y, dtype=bool)
    p = np.asarray(p, dtype=float)
    best, best_f1 = 0.5, 0.0
    for thr in sorted(THRESHOLDS, key=lambda t: (abs(t - 0.5), t)):
        f1 = prf(y, p >= thr)["f1"]
        if f1 > best_f1 + 1e-12:
            best, best_f1 = float(thr), f1
    return best


class _Constant:
    """Stand-in when the training window holds a single class."""

    def __init__(self, p: float):
        self.p = p

    def predict_proba(self, x) -> np.ndarray:
        return np.column_stack([np.full(len(x), 1 - self.p), np.full(len(x), self.p)])


def make_model(seed: int = SEED):
    """Gradient-boosted trees: shallow, regularised, no early stopping, fixed seed.

    Trees fit here because the signal is in interactions (hour x season x radiation x
    yesterday's price) and thresholds, they take missing values as they come, and a fit on
    two years of hours takes about a second.
    """
    from sklearn.ensemble import HistGradientBoostingClassifier

    return HistGradientBoostingClassifier(
        max_iter=200,
        learning_rate=0.05,
        max_depth=4,
        min_samples_leaf=40,
        l2_regularization=1.0,
        early_stopping=False,
        random_state=seed,
    )


def _fit_one(train: pd.DataFrame, features: list[str], seed: int):
    y = train["y"].to_numpy(dtype=bool)
    if y.all() or not y.any():
        return _Constant(float(y.mean()) if len(y) else 0.0)
    return make_model(seed).fit(train[features].to_numpy(dtype=float), y)


def _proba(model, rows: pd.DataFrame, features: list[str]) -> np.ndarray:
    return model.predict_proba(rows[features].to_numpy(dtype=float))[:, 1]


def fit(train: pd.DataFrame, features: list[str], seed: int = SEED):
    """Fit on ``train`` and pick the F1-maximising threshold from training data only.

    The threshold comes from a time-ordered hold-out inside the training window: a model
    fitted on the first 75% of training days scores the last 25%, and the best threshold on
    those days is kept. (In-sample probabilities of boosted trees are too sharp to tune on.)
    The returned model is then refitted on all training rows.
    """
    days = sorted(train["date"].unique())
    split = days[int(len(days) * 0.75)]
    head, tail = train[train["date"] < split], train[train["date"] >= split]
    threshold = 0.5
    if len(head) and tail["y"].any():
        threshold = best_f1_threshold(tail["y"], _proba(_fit_one(head, features, seed), tail, features))
    return _fit_one(train, features, seed), threshold


# ---- metrics ---------------------------------------------------------------------------


def prf(y, pred) -> dict:
    """Precision, recall and F1 for the positive class; 0 where the denominator is 0."""
    y = np.asarray(y, dtype=bool)
    pred = np.asarray(pred, dtype=bool)
    tp = int((y & pred).sum())
    fp = int((~y & pred).sum())
    fn = int((y & ~pred).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
    return {"precision": precision, "recall": recall, "f1": f1, "tp": tp, "fp": fp, "fn": fn}


def brier(y, p) -> float:
    """Mean squared error of the probability ``p`` against the 0/1 outcome."""
    return float(np.mean((np.asarray(p, dtype=float) - np.asarray(y, dtype=float)) ** 2))


def day_scores(dates, y, pred) -> dict:
    """Per-day scores.

    ``day_exact``: share of days whose predicted set of zero hours equals the actual set.
    ``day_exact_zero_days``: the same over days with at least one actual zero hour (a day
    without any is matched by predicting nothing). ``day_any``: share of days where
    "at least one zero hour" was called correctly.
    """
    g = pd.DataFrame(
        {"d": np.asarray(dates), "y": np.asarray(y, dtype=bool), "p": np.asarray(pred, dtype=bool)}
    )
    g["same"] = g["y"] == g["p"]
    by = g.groupby("d").agg(same=("same", "all"), y=("y", "any"), p=("p", "any"))
    zero_days = by[by["y"]]
    return {
        "days": int(len(by)),
        "zero_days": int(len(zero_days)),
        "day_exact": float(by["same"].mean()),
        "day_exact_zero_days": float(zero_days["same"].mean()) if len(zero_days) else None,
        "day_any": float((by["y"] == by["p"]).mean()),
    }


def evaluate(bt: pd.DataFrame, pred: str, prob: str) -> dict:
    """All metrics of one method over the rows of ``bt``."""
    if bt.empty:
        return {}
    out = prf(bt["y"], bt[pred])
    out["brier"] = brier(bt["y"], bt[prob])
    out.update(day_scores(bt["date"], bt["y"], bt[pred]))
    out["hours"] = int(len(bt))
    out["zero_hours"] = int(bt["y"].sum())
    out["predicted_hours"] = int(bt[pred].astype(bool).sum())
    return out


def reliability(y, p, bins: int = 10) -> list[dict]:
    """Calibration table: per probability bin, the mean forecast and the observed frequency."""
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    idx = np.minimum((p * bins).astype(int), bins - 1)
    rows = []
    for b in range(bins):
        sel = idx == b
        if sel.any():
            rows.append(
                {
                    "bin": f"{b / bins:.1f}–{(b + 1) / bins:.1f}",
                    "n": int(sel.sum()),
                    "mean_p": float(p[sel].mean()),
                    "observed": float(y[sel].mean()),
                }
            )
    return rows


def bootstrap_difference(bt: pd.DataFrame, a: str, b: str, *, n: int = 2000, seed: int = SEED) -> dict:
    """Day-block bootstrap of method ``a`` minus method ``b``: Brier score and F1.

    Whole days are resampled with replacement, since hours within a day are far from
    independent. Returns the point differences and 95% intervals.
    """
    stats = {}
    for key in (a, b):
        _, pred, prob = METHODS[key]
        y = bt["y"].to_numpy(dtype=bool)
        yhat = bt[pred].to_numpy(dtype=bool)
        cols = {
            "se": (bt[prob].to_numpy(dtype=float) - y) ** 2,
            "tp": y & yhat,
            "fp": ~y & yhat,
            "fn": y & ~yhat,
            "n": np.ones(len(bt)),
        }
        stats[key] = pd.DataFrame(cols).groupby(bt["date"].to_numpy()).sum().to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    days = len(stats[a])
    draws = rng.integers(0, days, size=(n, days))

    def scores(s: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        tot = s[draws].sum(axis=1)
        denom = 2 * tot[:, 1] + tot[:, 2] + tot[:, 3]
        return tot[:, 0] / tot[:, 4], np.divide(2 * tot[:, 1], denom, out=np.zeros(n), where=denom > 0)

    (ba, fa), (bb, fb) = scores(stats[a]), scores(stats[b])

    def point(s: np.ndarray) -> tuple[float, float]:
        t = s.sum(axis=0)
        return t[0] / t[4], (2 * t[1] / (2 * t[1] + t[2] + t[3]) if t[1] else 0.0)

    (pba, pfa), (pbb, pfb) = point(stats[a]), point(stats[b])
    return {
        "a": a,
        "b": b,
        "brier_diff": float(pba - pbb),
        "brier_ci": [float(q) for q in np.quantile(ba - bb, [0.025, 0.975])],
        "f1_diff": float(pfa - pfb),
        "f1_ci": [float(q) for q in np.quantile(fa - fb, [0.025, 0.975])],
        "resamples": n,
    }


# ---- backtest --------------------------------------------------------------------------


def backtest(
    table: pd.DataFrame,
    *,
    min_train_days: int = MIN_TRAIN_DAYS,
    retrain_every: int = RETRAIN_EVERY_DAYS,
    seed: int = SEED,
) -> pd.DataFrame:
    """Rolling-origin backtest over :func:`feature_table` output, one forecast origin per day.

    At origin D the training rows are the target days through D+1, the days whose prices are
    known. The window expands; the two models, the tuned thresholds and the climatology are
    refitted every ``retrain_every`` origins (weekly: the retrain costs seconds and the zero-hour
    season turns within weeks, so monthly would leave the model stale in March and April).
    The first forecast is made once ``min_train_days`` training days exist.
    """
    table = table.sort_values("ts_utc").reset_index(drop=True)
    out = []
    state = None
    since_fit = retrain_every
    for target in sorted(table["date"].unique()):
        origin = dt.date.fromisoformat(target) - dt.timedelta(days=HORIZON_DAYS)
        known_through = f"{origin + dt.timedelta(days=1):%Y-%m-%d}"
        train = table[table["date"] <= known_through]
        if train["date"].nunique() < min_train_days:
            continue
        if state is None or since_fit >= retrain_every:
            state = {
                "full": fit(train, FEATURES, seed),
                "nowx": fit(train, FEATURES_NO_WEATHER, seed),
                "clim": climatology(train),
                "trained_through": known_through,
            }
            since_fit = 0
        since_fit += 1
        rows = table[table["date"] == target]
        (m_full, thr_full), (m_nowx, thr_nowx) = state["full"], state["nowx"]
        out.append(
            pd.DataFrame(
                {
                    "origin": rows["origin"],
                    "date": rows["date"],
                    "hour": rows["hour"],
                    "ts_utc": rows["ts_utc"],
                    "price": rows["price"],
                    "y": rows["y"],
                    "p_model": _proba(m_full, rows, FEATURES),
                    "thr_model": thr_full,
                    "p_nowx": _proba(m_nowx, rows, FEATURES_NO_WEATHER),
                    "thr_nowx": thr_nowx,
                    "base_d1": rows["base_d1"],
                    "base_week": rows["base_week"],
                    "p_clim": predict_climatology(state["clim"], rows),
                    "trained_through": state["trained_through"],
                }
            )
        )
    if not out:
        raise ValueError(f"no forecast origin has {min_train_days} days of training data")
    result = add_predictions(pd.concat(out, ignore_index=True))
    result.attrs["config"] = {
        "min_train_days": int(min_train_days),
        "retrain_every_days": int(retrain_every),
        "seed": int(seed),
    }
    return result


def add_predictions(bt: pd.DataFrame) -> pd.DataFrame:
    """The 0/1 calls of every method in :data:`METHODS`, from the stored probabilities."""
    return bt.assign(
        pred_model=bt["p_model"] >= 0.5,
        pred_model_tuned=bt["p_model"] >= bt["thr_model"],
        pred_nowx=bt["p_nowx"] >= 0.5,
        pred_clim=bt["p_clim"] >= 0.5,
    )


# ---- results ---------------------------------------------------------------------------


def _hours(rows: pd.DataFrame, col: str) -> list[int]:
    return [int(h) for h in rows.loc[rows[col].astype(bool), "hour"]]


def _recall(rows: pd.DataFrame, pred: str) -> float | None:
    pos = rows[rows["y"]]
    return float(pos[pred].astype(bool).mean()) if len(pos) else None


def _day_context(table: pd.DataFrame, hourly: pd.DataFrame, date: str) -> dict:
    """Numbers that explain a day: the forecasts the model saw and what then happened."""
    f = table[table["date"] == date].iloc[0]
    prev = f"{dt.date.fromisoformat(date) - dt.timedelta(days=1):%Y-%m-%d}"

    def observed(day: str, col: str) -> float | None:
        g = hourly[(hourly["date"] == day) & ~hourly["grid_event"]]
        return float(g[col].sum() / g["demand"].sum()) if len(g) and g["demand"].sum() > 0 else None

    return {
        "forecast_rad": float(f["wx_rad_day"]),
        "forecast_rad_prev": float(f["wx_rad_day_d1"]),
        "forecast_wind": float(f["wx_wind_day"]),
        "forecast_wind_prev": float(f["wx_wind_day_d1"]),
        "d1_zero_hours": int(f["d1_zero_hours"]),
        "days_since_zero": int(f["days_since_zero"]),
        "solar_share": observed(date, "solar"),
        "solar_share_prev": observed(prev, "solar"),
        "wind_share": observed(date, "wind"),
        "wind_share_prev": observed(prev, "wind"),
    }


def _example(kind: str, bt: pd.DataFrame, table: pd.DataFrame, hourly: pd.DataFrame, date: str) -> dict:
    rows = bt[bt["date"] == date]
    return {
        "kind": kind,
        "date": date,
        "origin": rows["origin"].iloc[0],
        "actual_hours": _hours(rows, "y"),
        "model_hours": _hours(rows, "pred_model"),
        "d1_hours": _hours(rows, "base_d1"),
        "week_hours": _hours(rows, "base_week"),
        "max_p": float(rows["p_model"].max()),
        "min_price": float(rows["price"].min()),
        **_day_context(table, hourly, date),
    }


def failure_analysis(bt: pd.DataFrame, table: pd.DataFrame, hourly: pd.DataFrame) -> dict:
    """Where the model fails: onset days, streak breaks and hour-of-day groups, with examples.

    - Onset day: at least one zero hour after seven days without any.
    - Streak break: D+1 had zero hours (so "same as D+1" predicts some) but the day has none.
    - Example days are picked by rule, never by hand: the onset day with the most missed
      zero hours, the streak break with the most hours wrongly called, and the day with the
      most missed zero hours at night.
    """
    context = table.groupby("date")[["days_since_zero", "d1_zero_hours"]].first()
    night = set(HOUR_GROUPS["Night (20:00–07:59)"])
    day = bt.assign(
        fn=bt["y"] & ~bt["pred_model"],
        fp=~bt["y"] & bt["pred_model"],
        fn_night=bt["y"] & ~bt["pred_model"] & bt["hour"].isin(night),
    )
    by = day.groupby("date").agg(
        zero=("y", "sum"),
        model=("pred_model", "sum"),
        d1=("base_d1", "sum"),
        week=("base_week", "sum"),
        fn=("fn", "sum"),
        fp=("fp", "sum"),
        fn_night=("fn_night", "sum"),
    )
    by = by.join(context)
    onset = by[(by["zero"] > 0) & (by["days_since_zero"] > 7)]
    onset_rows = bt[bt["date"].isin(onset.index)]
    breaks = by[(by["d1"] > 0) & (by["zero"] == 0)]

    groups = {}
    for name, hours in HOUR_GROUPS.items():
        g = bt[bt["hour"].isin(hours)]
        m = prf(g["y"], g["pred_model"])
        groups[name] = {
            "zero_hours": int(g["y"].sum()),
            "model_precision": m["precision"],
            "model_recall": m["recall"],
            "d1_recall": _recall(g, "base_d1"),
            "week_recall": _recall(g, "base_week"),
        }

    examples = []
    used: set[str] = set()

    def pick(kind: str, frame: pd.DataFrame, by_col: str) -> None:
        frame = frame[(frame[by_col] > 0) & ~frame.index.isin(used)]
        if len(frame):
            # Largest first; ties go to the earliest date so the choice is reproducible.
            date = frame.sort_index().sort_values(by_col, ascending=False, kind="stable").index[0]
            used.add(date)
            examples.append(_example(kind, bt, table, hourly, date))

    pick("onset", onset, "fn")
    pick("streak_break", breaks, "model")
    pick("night", by, "fn_night")

    return {
        "onset": {
            "days": int(len(onset)),
            "zero_hours": int(onset["zero"].sum()),
            "model_days_flagged": int((onset["model"] > 0).sum()),
            "model_recall": _recall(onset_rows, "pred_model"),
            "d1_recall": _recall(onset_rows, "base_d1"),
            "week_recall": _recall(onset_rows, "base_week"),
        },
        "streak_break": {
            "days": int(len(breaks)),
            "model_days_flagged": int((breaks["model"] > 0).sum()),
            "model_false_hours": int(breaks["model"].sum()),
            "d1_false_hours": int(breaks["d1"].sum()),
        },
        "hour_groups": groups,
        "examples": examples,
    }


def _round(obj, digits: int = 4):
    if isinstance(obj, dict):
        return {k: _round(v, digits) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_round(v, digits) for v in obj]
    if isinstance(obj, float | np.floating):
        return None if not np.isfinite(obj) else round(float(obj), digits)
    if isinstance(obj, np.integer):
        return int(obj)
    return obj


def summarise(bt: pd.DataFrame, table: pd.DataFrame, hourly: pd.DataFrame) -> dict:
    """Everything the site, the case study and the notebook show, as a JSON-ready dict."""
    config = bt.attrs.get("config")
    if not config:
        raise ValueError("backtest settings missing: pass the frame returned by backtest()")
    month = pd.to_datetime(bt["date"]).dt.month

    def block(rows: pd.DataFrame) -> dict:
        return {key: evaluate(rows, pred, prob) for key, (_, pred, prob) in METHODS.items()}

    overall = block(bt)
    best = min(BASELINES, key=lambda k: overall[k]["brier"])
    best_f1 = max(BASELINES, key=lambda k: overall[k]["f1"])
    return _round(
        {
            "meta": {
                "target": "hourly OMIE day-ahead price (Spain) <= 0 EUR/MWh",
                "horizon_days": HORIZON_DAYS,
                "data_start": hourly["date"].min(),
                "data_end": hourly["date"].max(),
                "first_target": bt["date"].min(),
                "last_target": bt["date"].max(),
                "target_days": int(bt["date"].nunique()),
                "hours": int(len(bt)),
                "zero_hours": int(bt["y"].sum()),
                "min_train_days": config["min_train_days"],
                "retrain_every_days": config["retrain_every_days"],
                "retrains": int(bt["trained_through"].nunique()),
                "seed": config["seed"],
                "model": "sklearn HistGradientBoostingClassifier",
                "model_params": {
                    k: make_model(config["seed"]).get_params()[k]
                    for k in [
                        "max_iter",
                        "learning_rate",
                        "max_depth",
                        "min_samples_leaf",
                        "l2_regularization",
                    ]
                },
                "features": {"calendar": CALENDAR, "prices": PRICE, "weather": WEATHER},
                "weather_lead": weather.LEAD,
                "weather_points": list(weather.POINTS),
                "weather_attribution": weather.ATTRIBUTION,
                "tuned_threshold_median": float(bt.groupby("date")["thr_model"].first().median()),
                "tuned_threshold_range": [float(bt["thr_model"].min()), float(bt["thr_model"].max())],
            },
            "labels": {key: label for key, (label, _, _) in METHODS.items()},
            "overall": overall,
            "by_season": {name: block(bt[month.isin(months).to_numpy()]) for name, months in SEASONS.items()},
            "best_baseline": {"brier": best, "f1": best_f1},
            "vs_baselines": {b: bootstrap_difference(bt, "model", b) for b in BASELINES},
            "vs_no_weather": bootstrap_difference(bt, "model", "model_no_weather"),
            "reliability": reliability(bt["y"], bt["p_model"]),
            "failures": failure_analysis(bt, table, hourly),
        }
    )


def beats_baselines(results: dict) -> bool:
    """True if the model (p >= 0.5) has both a higher F1 and a lower Brier score than every baseline."""
    o = results["overall"]
    return all(o["model"]["f1"] > o[b]["f1"] and o["model"]["brier"] < o[b]["brier"] for b in BASELINES)


def load_results(path: Path = RESULTS) -> dict:
    """The committed backtest results (written by ``scripts/backtest_forecast.py``)."""
    return json.loads(path.read_text(encoding="utf-8"))
