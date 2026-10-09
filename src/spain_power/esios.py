"""Optional ESIOS (REE) client. Requires a personal token in ``ESIOS_TOKEN``.

Not used by default: everything in this repo runs on token-free sources (OMIE + REE).
Request a token at https://www.esios.ree.es/es/pagina/api if you want ESIOS indicators,
e.g. 600 (day-ahead SPOT price, Spain) or 1001 (PVPC).
"""

from __future__ import annotations

import json
import os

import pandas as pd

from .http import get_text

BASE = "https://api.esios.ree.es/indicators/{id}"


def available() -> bool:
    return bool(os.environ.get("ESIOS_TOKEN"))


def fetch_indicator(indicator: int, start: str, end: str, geo_id: int | None = 3) -> pd.DataFrame:
    token = os.environ.get("ESIOS_TOKEN")
    if not token:
        raise RuntimeError("ESIOS_TOKEN is not set; ESIOS is optional and not needed for this project")
    text = get_text(
        BASE.format(id=indicator),
        params={"start_date": start, "end_date": end},
        headers={"x-api-key": token, "Accept": "application/json; application/vnd.esios-api-v1+json"},
    )
    vals = pd.DataFrame(json.loads(text)["indicator"]["values"])
    if geo_id is not None and "geo_id" in vals:
        vals = vals[vals["geo_id"] == geo_id]
    vals["ts_utc"] = pd.to_datetime(vals["datetime_utc"], utc=True)
    return vals[["ts_utc", "value"]]
