"""Per-day parquet cache under data/raw and a combined hourly table under data/processed."""

from __future__ import annotations

import datetime as dt
import logging
import os
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from . import omie, ree
from .transform import build_hourly, expected_hours

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed" / "hourly.parquet"

SOURCES: dict[str, tuple[Callable[[dt.date], pd.DataFrame], Callable[[pd.DataFrame], pd.DataFrame]]] = {
    "omie": (omie.fetch_day, omie.to_hourly),
    "ree": (ree.fetch_day, ree.to_hourly),
}


def daterange(start: dt.date, end: dt.date) -> list[dt.date]:
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def _path(source: str, day: dt.date, raw: Path) -> Path:
    return raw / source / f"{day:%Y%m%d}.parquet"


def _complete(path: Path, day: dt.date) -> bool:
    """A cached day counts as done only if it holds every clock hour of that day."""
    if not path.exists():
        return False
    try:
        return len(pd.read_parquet(path, columns=["ts_utc"])) >= expected_hours(f"{day:%Y-%m-%d}")
    except Exception:  # noqa: BLE001 - unreadable file: refetch it
        return False


def _write_atomic(df: pd.DataFrame, path: Path) -> None:
    tmp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def fetch_range(
    source: str,
    start: dt.date,
    end: dt.date,
    *,
    raw: Path = RAW,
    force_recent_days: int = 2,
    workers: int = 6,
) -> list[dt.date]:
    """Download missing days (and re-fetch the most recent ones). Returns failed days."""
    fetch, to_hourly = SOURCES[source]
    (raw / source).mkdir(parents=True, exist_ok=True)
    recent = end - dt.timedelta(days=force_recent_days)
    todo = [d for d in daterange(start, end) if d > recent or not _complete(_path(source, d, raw), d)]
    failed: list[dt.date] = []

    def one(day: dt.date) -> None:
        try:
            hourly = to_hourly(fetch(day))
            if hourly.empty:
                raise ValueError("no rows")
            # Partial days (e.g. today) are cached but stay "incomplete", so they are refetched.
            _write_atomic(hourly, _path(source, day, raw))
        except Exception as e:  # noqa: BLE001 - log and continue, report at the end
            log.warning("%s %s failed: %s", source, day, e)
            failed.append(day)

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, todo))
    log.info("%s: fetched %d days, %d failed", source, len(todo) - len(failed), len(failed))
    return sorted(failed)


def load_source(
    source: str, raw: Path = RAW, start: dt.date | None = None, end: dt.date | None = None
) -> pd.DataFrame:
    files = sorted((raw / source).glob("*.parquet"))
    if start or end:
        lo = f"{start:%Y%m%d}" if start else "0"
        hi = f"{end:%Y%m%d}" if end else "9"
        files = [f for f in files if lo <= f.stem <= hi]
    if not files:
        raise FileNotFoundError(f"no cached {source} files under {raw / source}")
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    return df.groupby("ts_utc", as_index=False).mean(numeric_only=True)


def daily_path(raw: Path = RAW) -> Path:
    return raw / "redata_daily.parquet"


def fetch_daily(start: dt.date, end: dt.date, *, raw: Path = RAW, refetch_days: int = 45) -> pd.DataFrame:
    """Fetch REData daily totals and upsert them into the cache.

    Fetches from the first missing day (or ``end - refetch_days``, since REE revises recent
    days as metering firms up). New non-null values override cached ones; cached dates and
    values the new response does not cover are kept.
    """
    path = daily_path(raw)
    old = pd.read_parquet(path) if path.exists() else pd.DataFrame({"date": pd.Series(dtype=str)})
    old["date"] = old["date"].astype(str)
    have = set(old["date"])
    first_missing = next((d for d in daterange(start, end) if f"{d:%Y-%m-%d}" not in have), None)
    since = end - dt.timedelta(days=refetch_days)
    fetch_from = max(min(first_missing, since) if first_missing else since, start)
    new = ree.fetch_redata_daily(fetch_from, end)
    merged = upsert_daily(old, new)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(merged, path)
    return merged


def upsert_daily(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    old = old.assign(date=old["date"].astype(str)).set_index("date")
    new = new.assign(date=new["date"].astype(str)).set_index("date")
    merged = new.combine_first(old) if len(old) else new
    return merged.sort_index().reset_index()


def rebuild(
    raw: Path = RAW, out: Path = PROCESSED, start: dt.date | None = None, end: dt.date | None = None
) -> pd.DataFrame:
    dp = daily_path(raw)
    daily = pd.read_parquet(dp) if dp.exists() else None
    hourly = build_hourly(load_source("omie", raw, start, end), load_source("ree", raw, start, end), daily)
    out.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(hourly, out)
    return hourly


def load_hourly(path: Path = PROCESSED) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df["ts"] = pd.to_datetime(df["ts_utc"], utc=True).dt.tz_convert("Europe/Madrid")
    return df
