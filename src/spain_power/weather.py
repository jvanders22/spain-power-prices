"""Archived weather *forecasts* from Open-Meteo's Previous Runs API (free, no token).

Only used by the D+2 forecast (:mod:`spain_power.forecast`), and only with the
``_previous_day3`` fields: the value a model predicted 72 hours before the valid time. For any
hour of delivery day D+2 that forecast was issued on D-1 at the latest (23:00 local for the
last hour), so it is out well before the 13:00 cut-off on day D even with a model's
publication delay of several hours. ``_previous_day2`` (48 hours before) would come from a run
started *after* 13:00 on D for every afternoon hour of D+2, so it is not used. Observed or
reanalysis weather is never requested, and :func:`parse` rejects any other field.

Raw responses are cached as JSON under ``data/weather`` (one file per calendar quarter, all
points in one request) and committed, so the backtest and the tests run offline.

Weather data by Open-Meteo.com (https://open-meteo.com), licensed CC BY 4.0. The free API is
for non-commercial use.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path

import pandas as pd

from .http import get_text

log = logging.getLogger(__name__)
URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
CACHE = Path(__file__).resolve().parents[2] / "data" / "weather"
LEAD = "previous_day3"
VARIABLES = {"rad": "shortwave_radiation", "wind": "wind_speed_100m", "temp": "temperature_2m"}
ATTRIBUTION = "Weather forecasts by Open-Meteo.com (CC BY 4.0)"

# name: (latitude, longitude, used for). Solar points sit in the big PV regions (Andalucía,
# Extremadura, Castilla-La Mancha, Aragón); wind points in the Ebro valley, the northern
# meseta, Galicia and La Mancha.
POINTS: dict[str, tuple[float, float, frozenset[str]]] = {
    "seville": (37.39, -5.99, frozenset({"rad"})),
    "badajoz": (38.88, -6.97, frozenset({"rad"})),
    "ciudad_real": (38.99, -3.93, frozenset({"rad", "wind"})),
    "zaragoza": (41.65, -0.89, frozenset({"rad", "wind"})),
    "burgos": (42.34, -3.70, frozenset({"wind"})),
    "a_coruna": (43.36, -8.41, frozenset({"wind"})),
}
_GRID_TOLERANCE = 0.3  # degrees between a requested point and the grid cell the API returns


def fields() -> list[str]:
    """The hourly fields requested: every variable at the one permitted lead time."""
    return [f"{v}_{LEAD}" for v in VARIABLES.values()]


def quarters(start: dt.date, end: dt.date) -> list[tuple[str, dt.date, dt.date]]:
    """Calendar quarters overlapping ``[start, end]`` as ``(label, first day, last day)``."""
    out = []
    for p in pd.period_range(start, end, freq="Q"):
        out.append((f"{p.year}Q{p.quarter}", p.start_time.date(), p.end_time.date()))
    return out


def fetch_chunk(start: dt.date, end: dt.date) -> str:
    """One request for all points over ``[start, end]`` (UTC days); returns the raw JSON text."""
    params = {
        "latitude": ",".join(str(p[0]) for p in POINTS.values()),
        "longitude": ",".join(str(p[1]) for p in POINTS.values()),
        "start_date": f"{start:%Y-%m-%d}",
        "end_date": f"{end:%Y-%m-%d}",
        "hourly": ",".join(fields()),
        "timezone": "GMT",
        "wind_speed_unit": "ms",
    }
    return get_text(URL, params=params, timeout=120)


def parse(text: str) -> pd.DataFrame:
    """Raw response -> one row per UTC hour with ``<var>_<point>`` columns.

    Raises ``ValueError`` if the response holds any hourly field other than the
    ``_previous_day3`` ones, is not in UTC, or does not match :data:`POINTS`.
    """
    data = json.loads(text)
    places = data if isinstance(data, list) else [data]
    if len(places) != len(POINTS):
        raise ValueError(f"expected {len(POINTS)} points, got {len(places)}")
    cols: dict[str, pd.Series] = {}
    for (name, (lat, lon, _)), place in zip(POINTS.items(), places, strict=True):
        if abs(place["latitude"] - lat) > _GRID_TOLERANCE or abs(place["longitude"] - lon) > _GRID_TOLERANCE:
            raise ValueError(f"{name}: response is for {place['latitude']}, {place['longitude']}")
        if place.get("utc_offset_seconds") != 0:
            raise ValueError(f"{name}: response is not in UTC")
        hourly = dict(place["hourly"])
        ts = pd.to_datetime(hourly.pop("time"), utc=True)
        extra = sorted(set(hourly) - set(fields()))
        if extra:
            raise ValueError(f"{name}: only {LEAD} fields are allowed, got {extra}")
        for short, var in VARIABLES.items():
            cols[f"{short}_{name}"] = pd.Series(hourly[f"{var}_{LEAD}"], index=ts, dtype="float64")
    out = pd.DataFrame(cols)
    out.index.name = "ts_utc"
    return out.reset_index()


def _covers(path: Path, first: dt.date, last: dt.date) -> bool:
    if not path.exists():
        return False
    try:
        times = json.loads(path.read_text(encoding="utf-8"))[0]["hourly"]["time"]
    except (ValueError, KeyError, IndexError, TypeError):
        return False
    return bool(times) and times[0][:10] <= f"{first:%Y-%m-%d}" and times[-1][:10] >= f"{last:%Y-%m-%d}"


def load(start: dt.date, end: dt.date, *, cache: Path = CACHE, fetch: bool = True) -> pd.DataFrame:
    """Forecasts for every UTC hour of ``[start, end]``, from the cache where it covers them.

    A quarter is fetched (when ``fetch`` is true) only if its file is missing or does not span
    the days needed from it; otherwise a missing quarter raises ``FileNotFoundError``.
    """
    frames = []
    for label, q_start, q_end in quarters(start, end):
        path = cache / f"{LEAD}_{label}.json"
        first, last = max(q_start, start), min(q_end, end)
        if not _covers(path, first, last):
            if not fetch:
                raise FileNotFoundError(f"no cached weather for {first} to {last} at {path}")
            log.info("open-meteo: fetching %s (%s to %s)", label, first, last)
            text = fetch_chunk(first, last)
            parse(text)  # validate before caching
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        frames.append(parse(path.read_text(encoding="utf-8")))
    wx = pd.concat(frames, ignore_index=True).drop_duplicates("ts_utc").sort_values("ts_utc")
    lo = pd.Timestamp(start, tz="UTC")
    hi = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    return wx[(wx["ts_utc"] >= lo) & (wx["ts_utc"] < hi)].reset_index(drop=True)


def aggregate(wx: pd.DataFrame) -> pd.DataFrame:
    """National proxies per UTC hour from the point forecasts.

    ``wx_rad``: mean shortwave radiation over the solar points (W/m²). ``wx_wind``: mean 100 m
    wind speed over the wind points (m/s). ``wx_wind3``: mean of the cubed speed, capped at
    12 m/s (roughly rated power), since wind output goes with the cube. ``wx_temp``: mean 2 m
    temperature over all points (°C), a demand proxy.
    """

    def cols(short: str, use: str | None = None) -> list[str]:
        return [f"{short}_{n}" for n, p in POINTS.items() if use is None or use in p[2]]

    wind = wx[cols("wind", "wind")]
    return pd.DataFrame(
        {
            "ts_utc": wx["ts_utc"],
            "wx_rad": wx[cols("rad", "rad")].mean(axis=1),
            "wx_wind": wind.mean(axis=1),
            "wx_wind3": (wind.clip(upper=12.0) ** 3).mean(axis=1),
            "wx_temp": wx[cols("temp")].mean(axis=1),
        }
    )
