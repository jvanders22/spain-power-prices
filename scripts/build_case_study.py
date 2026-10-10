"""Generate docs/case_study.md and the README case-study section from the hourly table.

``--check`` writes nothing and exits 1 if either file is out of date (used in CI).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spain_power import cache, case_study  # noqa: E402


def outputs(df, readme: Path, doc: Path) -> dict[Path, str]:
    md = case_study.render(df)
    return {doc: md, readme: case_study.update_readme(readme.read_text(encoding="utf-8"), md)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="fail if the committed files are stale")
    ap.add_argument("--data", type=Path, default=cache.PROCESSED)
    ap.add_argument("--readme", type=Path, default=ROOT / "README.md")
    ap.add_argument("--doc", type=Path, default=ROOT / "docs" / "case_study.md")
    args = ap.parse_args(argv)

    stale = []
    for path, text in outputs(cache.load_hourly(args.data), args.readme, args.doc).items():
        if path.exists() and path.read_text(encoding="utf-8") == text:
            continue
        stale.append(path)
        if not args.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print(f"wrote {path}")
    if args.check and stale:
        print("out of date: " + ", ".join(str(p) for p in stale), file=sys.stderr)
        print("run: python scripts/build_case_study.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
