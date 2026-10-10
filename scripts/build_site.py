"""Build the static site (dashboard, case study, wholesale-vs-bill page) into ``_site/``.

The output is deterministic and self-contained, ready for GitHub Pages or any file server:
``python scripts/build_site.py && python -m http.server -d _site``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spain_power import cache, site  # noqa: E402


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "_site")
    ap.add_argument("--data", type=Path, default=cache.PROCESSED)
    args = ap.parse_args(argv)
    for path in site.build(cache.load_hourly(args.data), args.out):
        print(f"{path.stat().st_size:>10,}  {path}")


if __name__ == "__main__":
    main()
