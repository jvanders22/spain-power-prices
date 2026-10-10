"""D+2 forecast: information cut-off (no leakage), baselines, metrics and a small backtest."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from spain_power import forecast, weather

ORIGIN = dt.date(2025, 1, 15)
TZ = "Europe/Madrid"


def _ts(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz=TZ)


@pytest.fixture(scope="module")
def table(forecast_frames):
    return forecast.feature_table(*forecast_frames)


@pytest.fixture(scope="module")
def bt(table):
    return forecast.backtest(table, min_train_days=60, retrain_every=30)


# ---- cut-off and leakage ---------------------------------------------------------------


def test_available_at_limits():
    cut = forecast.available_at(ORIGIN)
    assert cut.target == dt.date(2025, 1, 17)
    assert cut.prices_before == _ts("2025-01-17 00:00")  # prices through the end of D+1
    assert cut.ree_before == _ts("2025-01-15 00:00")  # REE through the end of D-1
    assert cut.weather_before == _ts("2025-01-18 00:00")  # forecasts for the target day
    assert cut.weather_lead == "previous_day3"


def test_selected_inputs_end_at_the_cutoff(forecast_frames):
    hourly, wx = forecast_frames
    inp = forecast.select_inputs(hourly, wx, ORIGIN)
    assert inp.prices["ts_utc"].max() == _ts("2025-01-16 23:00")
    assert inp.ree["ts_utc"].max() == _ts("2025-01-14 23:00")
    assert inp.weather["ts_utc"].max() == _ts("2025-01-17 23:00")
    assert set(inp.prices.columns) == {"ts_utc", "price_es", "date", "hour"}
    assert "price_es" not in inp.ree.columns


def test_features_do_not_change_when_later_data_changes(forecast_frames):
    """Scramble everything after each cut-off: the features for the origin must be identical."""
    hourly, wx = forecast_frames
    cut = forecast.available_at(ORIGIN)
    want = forecast.build_features(hourly, wx, ORIGIN)
    rng = np.random.default_rng(7)

    h = hourly.copy()
    late_price = (h["ts_utc"] >= cut.prices_before).to_numpy()
    h.loc[late_price, "price_es"] = rng.uniform(-500, 500, late_price.sum())
    late_ree = (h["ts_utc"] >= cut.ree_before).to_numpy()
    for col in ["wind", "solar", "demand", "renewables_share", "hydro_gen", "nuclear", "solar_pv", "hydro"]:
        h.loc[late_ree, col] = rng.uniform(0, 1e5, late_ree.sum())
    w = wx.copy()
    late_wx = (w["ts_utc"] >= cut.weather_before).to_numpy()
    for col in ["wx_rad", "wx_wind", "wx_wind3", "wx_temp"]:
        w.loc[late_wx, col] = rng.uniform(0, 1e3, late_wx.sum())
    assert late_price.sum() > 1000 and late_ree.sum() > late_price.sum() and late_wx.sum() > 1000

    pd.testing.assert_frame_equal(forecast.build_features(h, w, ORIGIN), want)
    # Dropping the later rows altogether gives the same features too.
    pd.testing.assert_frame_equal(forecast.build_features(h[~late_price], w[~late_wx], ORIGIN), want)


def test_features_do_change_when_the_last_allowed_data_changes(forecast_frames):
    """The cut-off test has teeth: the last hours inside each limit feed the features."""
    hourly, wx = forecast_frames
    want = forecast.build_features(hourly, wx, ORIGIN)

    h = hourly.copy()
    h.loc[h["ts_utc"] == _ts("2025-01-16 23:00"), "price_es"] = -99.0
    got = forecast.build_features(h, wx, ORIGIN)
    assert got["p_d1"].iloc[23] == -99.0 and got["d1_min"].iloc[0] == -99.0
    assert bool(got["base_d1"].iloc[23]) and not want["base_d1"].iloc[23]

    h = hourly.copy()
    h.loc[h["ts_utc"] == _ts("2025-01-14 23:00"), "wind"] = 123456.0
    assert forecast.build_features(h, wx, ORIGIN)["r_wind_h"].iloc[23] == 123456.0

    w = wx.copy()
    w.loc[w["ts_utc"] == _ts("2025-01-17 23:00"), "wx_rad"] = 777.0
    assert forecast.build_features(hourly, w, ORIGIN)["wx_rad"].iloc[23] == 777.0


def test_ree_of_day_d_is_not_used_although_its_prices_are(forecast_frames):
    hourly, wx = forecast_frames
    want = forecast.build_features(hourly, wx, ORIGIN)
    h = hourly.copy()
    day_d = (h["date"] == "2025-01-15").to_numpy()
    h.loc[day_d, ["wind", "solar", "demand", "renewables_share", "hydro_gen", "nuclear"]] = 9e9
    pd.testing.assert_frame_equal(forecast.build_features(h, wx, ORIGIN), want)
    h.loc[day_d, "price_es"] = -1.0
    assert (forecast.build_features(h, wx, ORIGIN)["p_d2"] == -1.0).all()


def test_weather_inputs_are_previous_day3_only(forecast_frames):
    hourly, wx = forecast_frames
    assert weather.LEAD == "previous_day3"
    assert all(f.endswith("_previous_day3") for f in weather.fields())
    with pytest.raises(ValueError, match="unexpected weather columns"):
        forecast.select_inputs(hourly, wx.assign(wx_rad_observed=1.0), ORIGIN)


def test_feature_rows_and_columns(forecast_frames):
    hourly, wx = forecast_frames
    rows = forecast.build_features(hourly, wx, ORIGIN)
    assert len(rows) == 24 and rows["date"].eq("2025-01-17").all() and rows["origin"].eq("2025-01-15").all()
    assert rows["hour"].tolist() == list(range(24))
    assert set(forecast.FEATURES) <= set(rows.columns)
    assert not {"y", "price", "price_es"} & set(rows.columns)
    assert rows[forecast.FEATURES].notna().all().all()
    assert rows["dow"].eq(4).all() and rows["is_weekend"].eq(0).all()  # a Friday
    no_wx = forecast.build_features(hourly, None, ORIGIN)
    assert no_wx[forecast.WEATHER].isna().all().all()
    pd.testing.assert_frame_equal(no_wx[forecast.FEATURES_NO_WEATHER], rows[forecast.FEATURES_NO_WEATHER])


def test_blackout_hours_are_blanked_in_ree_inputs(forecast_frames):
    hourly, _ = forecast_frames
    h = hourly.assign(grid_event=(hourly["date"] == "2025-01-14") & (hourly["hour"] >= 12))
    ree = forecast.select_inputs(h, None, ORIGIN).ree
    event = (ree["date"] == "2025-01-14") & (ree["hour"] >= 12)
    assert ree.loc[event, "wind"].isna().all() and ree.loc[~event, "wind"].notna().all()


def test_target_hours_on_dst_days():
    assert len(forecast.target_hours(dt.date(2025, 3, 30))) == 23
    autumn = forecast.target_hours(dt.date(2025, 10, 26))
    assert len(autumn) == 25 and autumn["hour"].tolist().count(2) == 2
    assert autumn["ts_utc"].is_unique


# ---- baselines on a tiny series --------------------------------------------------------


def _tiny(zero: dict[str, list[int]], start: str = "2025-03-03", days: int = 14) -> pd.DataFrame:
    """Hourly prices of 50, except 0 or below at the given (date, hours)."""
    ts = pd.date_range(start, periods=days * 24, freq="h", tz=TZ)
    df = pd.DataFrame({"ts_utc": ts.tz_convert("UTC"), "date": ts.strftime("%Y-%m-%d"), "hour": ts.hour})
    df["price_es"] = 50.0
    for date, hours in zero.items():
        df.loc[(df["date"] == date) & df["hour"].isin(hours), "price_es"] = [-1.0, 0.0][: len(hours)]
    for col in ["wind", "solar", "demand", "renewables_share", "hydro_gen", "nuclear"]:
        df[col] = 1.0
    return df


def test_baselines_on_a_tiny_series():
    # Target 2025-03-14 (origin 03-12): D+1 is 03-13, the same weekday last week is 03-07.
    hourly = _tiny({"2025-03-13": [12, 13], "2025-03-07": [14], "2025-03-14": [9], "2025-03-12": [3]})
    rows = forecast.build_features(hourly, None, dt.date(2025, 3, 12))
    assert rows.loc[rows["base_d1"], "hour"].tolist() == [12, 13]  # -1 and exactly 0 both count
    assert rows.loc[rows["base_week"], "hour"].tolist() == [14]
    assert rows["d1_zero_hours"].eq(2).all() and rows["d2_zero_hours"].eq(1).all()
    assert rows["days_since_zero"].eq(1).all() and rows["d1_min"].eq(-1.0).all()
    assert rows["zshare7_h"].iloc[12] == pytest.approx(1 / 7) and rows["zshare7_h"].iloc[9] == 0
    # The target day's own zero hour (09:00) reaches the label only.
    out = forecast.attach_target(rows, hourly)
    assert out.loc[out["y"], "hour"].tolist() == [9]

    # A day with no history a week back: the baseline says "not zero" rather than failing.
    early = forecast.build_features(hourly, None, dt.date(2025, 3, 5))
    assert not early["base_week"].any() and early["p_d7"].isna().all()


def test_climatology_uses_training_frequencies_with_fallbacks():
    train = pd.DataFrame(
        {
            "date": ["2025-03-01"] * 2 + ["2025-03-02"] * 2 + ["2025-04-01"] * 2,
            "hour": [12, 13, 12, 13, 12, 13],
            "y": [True, False, False, False, True, True],
        }
    )
    table = forecast.climatology(train)
    rows = pd.DataFrame(
        {"date": ["2025-03-09", "2025-04-09", "2025-05-09", "2025-05-09"], "hour": [12, 13, 12, 7]}
    )
    # March 12h: 1 of 2. April 13h: 1 of 1. May is unseen: hour 12 overall is 2 of 3; hour 7
    # is unseen too, so the overall rate of 3 in 6.
    assert forecast.predict_climatology(table, rows).tolist() == pytest.approx([0.5, 1.0, 2 / 3, 0.5])


# ---- metrics vs hand-computed values ---------------------------------------------------


def test_precision_recall_f1_by_hand():
    y = [1, 1, 1, 0, 0, 0, 0, 0]
    pred = [1, 1, 0, 1, 0, 0, 0, 0]
    m = forecast.prf(y, pred)
    assert (m["tp"], m["fp"], m["fn"]) == (2, 1, 1)
    assert m["precision"] == pytest.approx(2 / 3) and m["recall"] == pytest.approx(2 / 3)
    assert m["f1"] == pytest.approx(2 / 3)
    m = forecast.prf([1, 1, 1, 1, 0], [1, 0, 0, 0, 0])
    assert m["precision"] == 1.0 and m["recall"] == 0.25 and m["f1"] == pytest.approx(0.4)
    assert forecast.prf([0, 0], [0, 0]) == {
        "precision": 0.0,
        "recall": 0.0,
        "f1": 0.0,
        "tp": 0,
        "fp": 0,
        "fn": 0,
    }
    assert forecast.prf([1, 0], [0, 0])["f1"] == 0.0


def test_brier_by_hand():
    assert forecast.brier([1, 0, 1, 0], [0.9, 0.1, 0.4, 0.6]) == pytest.approx(
        (0.01 + 0.01 + 0.36 + 0.36) / 4
    )
    assert forecast.brier([1, 0, 1], [True, True, False]) == pytest.approx(2 / 3)  # a 0/1 baseline


def test_day_scores_by_hand():
    dates = ["a"] * 3 + ["b"] * 3 + ["c"] * 3 + ["d"] * 3
    y = [0, 1, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0]
    pred = [0, 1, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0]
    s = forecast.day_scores(dates, y, pred)
    # a: exact. b: exact (nothing, nothing). c: wrong hour, but "has a zero hour" is right.
    # d: false alarm.
    assert s["days"] == 4 and s["zero_days"] == 2
    assert s["day_exact"] == 0.5 and s["day_exact_zero_days"] == 0.5 and s["day_any"] == 0.75
    assert forecast.day_scores(["a", "a"], [0, 0], [0, 0])["day_exact_zero_days"] is None


def test_reliability_bins_by_hand():
    rows = forecast.reliability([0, 1, 1, 1, 0], [0.05, 0.08, 0.95, 1.0, 0.55])
    assert [(r["bin"], r["n"]) for r in rows] == [("0.0–0.1", 2), ("0.5–0.6", 1), ("0.9–1.0", 2)]
    assert rows[0]["mean_p"] == pytest.approx(0.065) and rows[0]["observed"] == 0.5
    assert rows[2]["observed"] == 1.0


def test_best_f1_threshold():
    y = [0, 0, 0, 1, 1, 0]
    p = [0.05, 0.10, 0.20, 0.30, 0.90, 0.25]
    # Any threshold in (0.25, 0.30] gives F1 = 1; the one nearest 0.5 is 0.30.
    assert forecast.best_f1_threshold(y, p) == pytest.approx(0.30)
    assert forecast.best_f1_threshold([0, 0], [0.9, 0.1]) == 0.5
    assert forecast.best_f1_threshold([1, 0], [0.01, 0.01]) == 0.5


def test_evaluate_combines_the_metrics():
    bt = pd.DataFrame(
        {
            "date": ["a", "a", "b", "b"],
            "y": [True, False, False, False],
            "pred": [True, True, False, False],
            "p": [0.8, 0.6, 0.1, 0.0],
        }
    )
    m = forecast.evaluate(bt, "pred", "p")
    assert m["precision"] == 0.5 and m["recall"] == 1.0 and m["f1"] == pytest.approx(2 / 3)
    assert m["brier"] == pytest.approx((0.04 + 0.36 + 0.01) / 4)
    assert (m["hours"], m["zero_hours"], m["predicted_hours"]) == (4, 1, 2)
    assert m["day_exact"] == 0.5 and m["day_any"] == 1.0
    assert forecast.evaluate(bt.iloc[:0], "pred", "p") == {}


def test_bootstrap_difference_point_values_and_seed(bt):
    d = forecast.bootstrap_difference(bt, "model", "same_as_d1", n=200)
    model = forecast.evaluate(bt, "pred_model", "p_model")
    base = forecast.evaluate(bt, "base_d1", "base_d1")
    assert d["brier_diff"] == pytest.approx(model["brier"] - base["brier"])
    assert d["f1_diff"] == pytest.approx(model["f1"] - base["f1"])
    assert d["brier_ci"][0] <= d["brier_diff"] <= d["brier_ci"][1]
    assert d == forecast.bootstrap_difference(bt, "model", "same_as_d1", n=200)


# ---- backtest --------------------------------------------------------------------------


def test_feature_table_targets(table, forecast_frames):
    hourly, _ = forecast_frames
    assert table["date"].min() == "2024-10-08"  # a full week of price history first
    merged = table.merge(hourly[["ts_utc", "price_es"]], on="ts_utc")
    assert len(merged) == len(table) and (merged["price"] == merged["price_es"]).all()
    assert (table["y"] == (table["price"] <= 0)).all() and table["y"].any()
    assert (pd.to_datetime(table["date"]) - pd.to_datetime(table["origin"])).dt.days.eq(2).all()


def test_backtest_trains_only_on_days_known_at_the_origin(bt):
    origin = pd.to_datetime(bt["origin"])
    trained = pd.to_datetime(bt["trained_through"])
    assert (trained <= origin + pd.Timedelta(days=1)).all()  # labels through D+1 at most
    assert (pd.to_datetime(bt["date"]) - trained).dt.days.min() == 1
    assert (pd.to_datetime(bt["date"]) - trained).dt.days.max() == 30  # retrain_every=30
    # 60 training days (8 Oct to 6 Dec) are known at origin 5 Dec, whose target is 7 Dec.
    assert bt["date"].min() == "2024-12-07"
    sizes = bt.groupby("date").size()
    assert sizes["2025-03-30"] == 23 and sizes.drop("2025-03-30").eq(24).all()  # DST day
    assert bt["p_model"].between(0, 1).all() and bt["p_clim"].between(0, 1).all()
    assert bt["thr_model"].between(0.05, 0.95).all()


def test_backtest_is_deterministic_and_learns_the_synthetic_pattern(table, bt):
    again = forecast.backtest(table, min_train_days=60, retrain_every=30)
    pd.testing.assert_frame_equal(again, bt)
    model = forecast.evaluate(bt, "pred_model", "p_model")
    clim = forecast.evaluate(bt, "pred_clim", "p_clim")
    assert model["brier"] < clim["brier"]


def test_backtest_needs_enough_training_days(table):
    with pytest.raises(ValueError, match="no forecast origin"):
        forecast.backtest(table, min_train_days=10_000)


def test_summarise_matches_the_results_fixture(bt, table, forecast_frames, forecast_results):
    """The small results fixture the site tests render is what ``summarise`` produces."""
    hourly, _ = forecast_frames
    got = forecast.summarise(bt, table, hourly)
    assert set(got) == set(forecast_results)
    assert set(got["overall"]) == set(forecast.METHODS) == set(got["labels"])
    assert set(got["by_season"]) == set(forecast.SEASONS)
    assert got["by_season"]["Summer (Jun–Aug)"]["model"] == {}
    assert got["meta"] == forecast_results["meta"]
    assert got["overall"]["model"].keys() == forecast_results["overall"]["model"].keys()
    assert got["overall"]["same_as_d1"] == forecast_results["overall"]["same_as_d1"]
    assert got["overall"]["model"]["f1"] == pytest.approx(
        forecast_results["overall"]["model"]["f1"], abs=0.05
    )
    for e in got["failures"]["examples"]:
        assert e["kind"] in {"onset", "streak_break", "night"} and e["date"] in set(bt["date"])


def test_beats_baselines(forecast_results):
    assert forecast.beats_baselines(forecast_results)
    forecast_results["overall"]["model"]["brier"] = 0.9
    assert not forecast.beats_baselines(forecast_results)


def test_committed_results_match_the_committed_backtest():
    """docs/forecast_results.json and the backtest table come from the same run."""
    if not (forecast.RESULTS.exists() and forecast.BACKTEST.exists()):
        pytest.skip("no committed backtest")
    results = forecast.load_results()
    bt = pd.read_parquet(forecast.BACKTEST)
    assert results["meta"]["hours"] == len(bt) and results["meta"]["zero_hours"] == int(bt["y"].sum())
    assert (pd.to_datetime(bt["date"]) - pd.to_datetime(bt["origin"])).dt.days.eq(2).all()
    assert (pd.to_datetime(bt["trained_through"]) < pd.to_datetime(bt["date"])).all()
    for key, (_, pred, prob) in forecast.METHODS.items():
        m = forecast.evaluate(bt, pred, prob)
        for name in ["precision", "recall", "f1", "brier", "day_exact", "day_any"]:
            assert results["overall"][key][name] == pytest.approx(m[name], abs=1e-4), (key, name)
