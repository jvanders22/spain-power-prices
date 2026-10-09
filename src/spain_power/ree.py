"""Red Eléctrica (REE) public data, no token required.

1. Hourly generation mix + demand for the peninsular system: the public endpoint behind
   REE's "Seguimiento de la demanda" viewer (demanda.ree.es), 5-minute resolution, JSONP.
   The REData API (apidatos.ree.es) only serves the generation structure at daily
   granularity, so it is used for the daily cross-check below, not for the hourly analysis.
2. Daily renewable vs non-renewable generation from REData (apidatos.ree.es).
"""

from __future__ import annotations

import datetime as dt
import json

import numpy as np
import pandas as pd

from .http import get_text

TZ = "Europe/Madrid"
DEMANDA_URL = "https://demanda.ree.es/WSvisionaMovilesPeninsulaRest/resources/demandaGeneracionPeninsula"
REDATA_URL = "https://apidatos.ree.es/en/datos/generacion/evolucion-renovable-no-renovable"

# demanda.ree.es field codes (MW, peninsular system)
FIELDS = {
    "dem": "demand",
    "eol": "wind",
    "solFot": "solar_pv",
    "solTer": "solar_thermal",
    "hid": "hydro",
    "nuc": "nuclear",
    "cc": "combined_cycle",
    "car": "coal",
    "cogenResto": "cogeneration_other",
}
RENEWABLE = ["wind", "solar_pv", "solar_thermal", "hydro"]
REQUIRED = ["ts", "dem", "eol", "solFot", "hid"]  # a feed without these is broken, not zero


def _localize(ts: pd.Series) -> pd.Series:
    """Localize REE naive local stamps. On the autumn DST day REE labels the repeated
    hour ``2A`` (first pass, CEST) and ``2B`` (second pass, CET)."""
    first = ts.str.contains(" 2A:", regex=False)
    second = ts.str.contains(" 2B:", regex=False)
    clean = ts.str.replace(" 2A:", " 02:", regex=False).str.replace(" 2B:", " 02:", regex=False)
    naive = pd.to_datetime(clean, format="%Y-%m-%d %H:%M")
    # ambiguous=True means DST (CEST); False means standard time (CET).
    amb = np.where(second, False, True)
    out = naive.dt.tz_localize(TZ, ambiguous=amb, nonexistent="NaT")
    out[first] = naive[first].dt.tz_localize(TZ, ambiguous=np.ones(first.sum(), bool))
    return out


def parse_demanda(text: str, day: dt.date) -> pd.DataFrame:
    """Parse the JSONP payload, keep rows on ``day`` (local), return 5-min tz-aware rows."""
    payload = json.loads(text[text.index("(") + 1 : text.rindex(")")])
    df = pd.DataFrame(payload["valoresHorariosGeneracion"])
    if df.empty:
        raise ValueError(f"no REE rows for {day}")
    missing = [k for k in REQUIRED if k not in df.columns]
    if missing:
        raise ValueError(f"REE payload for {day} is missing required fields {missing}")
    df = df[[c for c in ["ts", *FIELDS] if c in df.columns]].rename(columns=FIELDS)
    for c in FIELDS.values():
        if c not in df.columns:  # optional technologies (e.g. coal) may be absent: zero output
            df[c] = 0.0
    df["ts"] = _localize(df["ts"].astype(str))
    df = df.dropna(subset=["ts"])
    df = df[df["ts"].dt.date == day]
    if df.empty:
        raise ValueError(f"no REE rows on {day}")
    return df[["ts", *FIELDS.values()]].reset_index(drop=True)


def fetch_day(day: dt.date) -> pd.DataFrame:
    text = get_text(DEMANDA_URL, params={"curva": "DEMANDAAU", "fecha": f"{day:%Y-%m-%d}"})
    return parse_demanda(text, day)


def to_hourly(df: pd.DataFrame) -> pd.DataFrame:
    """Mean MW per clock hour (equals MWh for that hour), UTC-indexed."""
    cols = list(FIELDS.values())
    utc = df["ts"].dt.tz_convert("UTC").dt.floor("h")
    h = df.groupby(utc)[cols].mean()
    h.index.name = "ts_utc"
    return h.reset_index()


def parse_redata_renewables(text: str) -> pd.DataFrame:
    d = json.loads(text)
    if "errors" in d:
        raise RuntimeError(d["errors"][0].get("detail"))
    frames = []
    for item in d["included"]:
        name = item["attributes"]["title"].lower().replace(" ", "_").replace("-", "_")
        v = pd.DataFrame(item["attributes"]["values"])
        v["date"] = pd.to_datetime(v["datetime"].str[:10]).dt.date
        frames.append(v.set_index("date")["value"].rename(name))
    return pd.concat(frames, axis=1).reset_index()


def fetch_redata_renewables(start: dt.date, end: dt.date) -> pd.DataFrame:
    """Daily renewable / non-renewable generation (MWh), national. Chunked by year."""
    out = []
    cur = start
    while cur <= end:
        stop = min(end, dt.date(cur.year, 12, 31))
        text = get_text(
            REDATA_URL,
            params={
                "start_date": f"{cur:%Y-%m-%d}T00:00",
                "end_date": f"{stop:%Y-%m-%d}T23:59",
                "time_trunc": "day",
            },
        )
        out.append(parse_redata_renewables(text))
        cur = stop + dt.timedelta(days=1)
    return pd.concat(out, ignore_index=True)


# --- REData daily totals (peninsular), used to calibrate the real-time hourly profiles ---------

REDATA_STRUCTURE_URL = "https://apidatos.ree.es/en/datos/generacion/estructura-generacion"
REDATA_DEMAND_URL = "https://apidatos.ree.es/en/datos/demanda/evolucion"
PENINSULAR = {"geo_trunc": "electric_system", "geo_limit": "peninsular", "geo_ids": "8741"}
REDATA_TECH = {
    "Wind": "wind",
    "Solar photovoltaic": "solar_pv",
    "Thermal solar": "solar_thermal",
    "Hydro": "hydro_gen",
    "Demand": "demand",
}


def parse_redata_daily(text: str) -> pd.DataFrame:
    """Parse a REData daily response into long rows (date, column, mwh) for the techs we use."""
    d = json.loads(text)
    if "errors" in d:
        raise RuntimeError(d["errors"][0].get("detail"))
    rows = []
    for item in d["included"]:
        col = REDATA_TECH.get(item["type"]) or REDATA_TECH.get(item["attributes"].get("title", ""))
        if not col:
            continue
        for v in item["attributes"]["values"]:
            rows.append((v["datetime"][:10], col, float(v["value"])))
    return pd.DataFrame(rows, columns=["date", "column", "mwh"])


def fetch_redata_daily(start: dt.date, end: dt.date) -> pd.DataFrame:
    """Daily MWh per technology + demand for the peninsular system, wide by column.

    The REData API caps daily requests at roughly one year, so this chunks by calendar year.
    """
    out = []
    cur = start
    while cur <= end:
        stop = min(end, dt.date(cur.year, 12, 31))
        params = {
            "start_date": f"{cur:%Y-%m-%d}T00:00",
            "end_date": f"{stop:%Y-%m-%d}T23:59",
            "time_trunc": "day",
            **PENINSULAR,
        }
        for url in (REDATA_STRUCTURE_URL, REDATA_DEMAND_URL):
            out.append(parse_redata_daily(get_text(url, params=params)))
        cur = stop + dt.timedelta(days=1)
    long = pd.concat(out, ignore_index=True)
    return long.pivot_table(index="date", columns="column", values="mwh", aggfunc="last").reset_index()
