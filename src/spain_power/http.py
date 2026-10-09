from __future__ import annotations

import time

import requests

UA = {"User-Agent": "spain-power-prices/0.1 (portfolio project; github.com/jvanders22)"}


def get_text(
    url: str, *, params: dict | None = None, headers: dict | None = None, retries: int = 4, timeout: int = 30
) -> str:
    last: Exception | None = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, headers={**UA, **(headers or {})}, timeout=timeout)
            if r.status_code == 200 and r.text.strip():
                return r.text
            last = RuntimeError(f"HTTP {r.status_code} for {r.url}")
            if r.status_code == 404:
                break
        except requests.RequestException as e:  # pragma: no cover - network
            last = e
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"failed to fetch {url}: {last}")
