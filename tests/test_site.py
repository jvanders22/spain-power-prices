"""Static site: smoke test of the build and Node parity of the page's KPI logic with Python."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from conftest import synthetic_inputs

from spain_power import site, transform
from spain_power.cache import PROCESSED, load_hourly
from spain_power.transform import build_hourly

PAGES = ["index.html", "case-study.html", "wholesale-vs-bill.html"]

# Loads the built page's data and JS; BODY prints JSON for [start, end, threshold] triples.
NODE = """
const fs = require("fs"), path = require("path");
const [dir, ...args] = process.argv.slice(1);
const html = fs.readFileSync(path.join(dir, "index.html"), "utf8");
const blob = html.match(/<script id="site-data" type="application\\/json">(.*?)<\\/script>/s)[1];
const sp = require(path.resolve(dir, "assets/app.js"));
const D = sp.prepare(JSON.parse(blob).data);
const out = [];
for (let i = 0; i < args.length; i += 3) {
  const [i0, i1] = sp.range(D, args[i], args[i + 1]);
  const threshold = Number(args[i + 2]);
  out.push(BODY);
}
console.log(JSON.stringify(out));
"""
NODE_KPIS = NODE.replace("BODY", "sp.kpis(D, i0, i1, threshold)")
NODE_CHARTS = NODE.replace(
    "BODY",
    """{
    buckets: sp.buckets(D, i0, i1),
    heatmap: sp.heatmap(D, i0, i1, threshold),
    top: sp.topCells(sp.heatmap(D, i0, i1, threshold), 5),
    capture: sp.capture(D, i0, i1),
  }""",
)


def _node(script: str, out, cases) -> list:
    args = [str(a) for case in cases for a in case]
    run = subprocess.run(
        ["node", "-e", script, str(out), *args], capture_output=True, text=True, check=True, timeout=120
    )
    return json.loads(run.stdout)


def _assert_charts_match_python(df, threshold: float, js: dict) -> None:
    """Bucket means, heatmap counts and monthly capture prices from the page's JS vs transform."""
    b = transform.share_buckets(df)
    assert [r["label"] for r in js["buckets"]] == list(b.index)
    assert [r["count"] for r in js["buckets"]] == b["count"].tolist()
    assert [r["mean"] for r in js["buckets"]] == pytest.approx(b["mean"].tolist(), abs=1e-3)

    h = transform.negative_hours(df, threshold).reindex(columns=range(24), fill_value=0)
    assert js["heatmap"]["months"] == list(h.index)
    assert js["heatmap"]["z"] == h.to_numpy().tolist()
    cells = h.stack()
    best = sorted(cells[cells > 0].items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    assert [(c["month"], c["hour"], c["count"]) for c in js["top"]] == [(m, hr, n) for (m, hr), n in best]

    c = transform.capture_prices(df)
    assert js["capture"]["months"] == list(c.index)
    for col in ["baseload", "solar_capture", "wind_capture"]:
        assert js["capture"][col] == pytest.approx(c[col].tolist(), abs=0.01), col


@pytest.fixture(scope="module")
def frame():
    # Covers both comparison windows in findings.WINDOWS in full, which the case study needs.
    return build_hourly(*synthetic_inputs("2024-10-01", "2026-10-09 23:00"))


@pytest.fixture(scope="module")
def built(frame, tmp_path_factory):
    out = tmp_path_factory.mktemp("site")
    site.build(frame, out)
    return out


def _blob(out) -> dict:
    html = (out / "index.html").read_text(encoding="utf-8")
    return json.loads(
        re.search(r'<script id="site-data" type="application/json">(.*?)</script>', html, re.S)[1]
    )


def test_pages_and_assets_exist(built, frame):
    for name in [*PAGES, "assets/plotly.min.js", "assets/app.js", "data/hourly.csv"]:
        assert (built / name).stat().st_size > 0, name
    csv = (built / "data" / "hourly.csv").read_text(encoding="utf-8").splitlines()
    assert len(csv) == len(frame) + 1
    assert "price_es" in csv[0] and "renewables_share" in csv[0]


def test_pages_are_self_contained(built):
    for name in PAGES:
        html = (built / name).read_text(encoding="utf-8")
        assert "http://" not in html, name
        # Scripts, styles and images are local; https only appears in <a href> links.
        for url in re.findall(r'<(?:script|link|img|iframe)\b[^>]*?(?:src|href)="([^"]+)"', html):
            assert url.startswith(("assets/", "data:")), (name, url)
        assert set(re.findall(r'"(https://[^"]+)"', html)) == set(
            re.findall(r'<a href="(https://[^"]+)"', html)
        )
        for href in ["index.html", "case-study.html", "wholesale-vs-bill.html", site.REPO_URL]:
            assert f'href="{href}"' in html, (name, href)
        assert site.ATTRIBUTION in html
        assert "Data through 9 Oct 2026" in html


def test_embedded_data_parses_and_matches_frame(built, frame):
    blob = _blob(built)
    data = blob["data"]
    n = len(frame)
    columns = ["di", "hour", "price", "demand", "solar", "wind", "ren", "share", "bucket"]
    assert all(len(data[k]) == n for k in columns)
    assert data["dates"][0] == "2024-10-01" and data["dates"][-1] == "2026-10-09"
    assert [data["dates"][i] for i in data["di"][:25:24]] == ["2024-10-01", "2024-10-02"]
    assert data["price"] == pytest.approx(frame["price_es"].tolist(), abs=1e-4)
    assert set(blob["figs"]) == {"scatter", "heatmap", "capture", "profile"}
    for spec in blob["figs"].values():
        assert spec["layout"]["title"]["text"]
        assert not any(k in trace for trace in spec["data"] for k in ("x", "y", "z", "customdata"))


def test_grid_event_hours_are_flagged(frame):
    ev = site.payload(frame)["ev"]
    assert len(ev) == 12  # the blackout afternoon, 28 Apr 2025 12:00-23:59
    assert ev == frame.index[frame["grid_event"]].tolist()


def test_buckets_come_from_the_unrounded_share(frame):
    # 0.29996 and 0.30004 both round to 0.3 at 4 dp but sit either side of the 30% edge.
    df = frame.head(6).copy()
    df["renewables_share"] = [0.29996, 0.30004, 0.0, 1.49999, 1.5, float("nan")]
    data = site.payload(df)
    assert data["share"] == [0.3, 0.3, 0.0, 1.5, 1.5, None]
    assert data["bucket"] == [2, 3, 0, 14, -1, -1]
    assert transform.share_buckets(df)["count"].to_dict() == {
        "0%-10%": 1,
        "20%-30%": 1,
        "30%-40%": 1,
        "140%-150%": 1,
    }


def test_expected_kpis_are_embedded(built, frame):
    html = (built / "index.html").read_text(encoding="utf-8")
    want = site.expected_kpis(frame)
    k = transform.kpis(frame)
    assert want["avg"] == k["avg_price"] and want["rate"] == k["solar_capture_rate"] * 100
    for key in ["avg", "low", "pct", "ren", "capture", "rate"]:
        got = float(re.search(rf'id="kpi-{key}" data-expected="([^"]+)"', html)[1])
        assert got == pytest.approx(want[key], abs=1e-4), key


def test_build_is_deterministic(built, frame, tmp_path):
    site.build(frame, tmp_path)
    first = sorted(p.relative_to(built) for p in built.rglob("*") if p.is_file())
    assert first == sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file())
    for rel in first:
        assert (built / rel).read_bytes() == (tmp_path / rel).read_bytes(), rel


def test_case_study_and_wholesale_pages(built):
    cs = (built / "case-study.html").read_text(encoding="utf-8")
    assert "<h1>Case study" in cs and "<h2>Findings</h2>" in cs and "<li><strong>Prices:</strong>" in cs
    wb = (built / "wholesale-vs-bill.html").read_text(encoding="utf-8")
    assert "97.553" in wb and "BOE-A-2025-26348" in wb and "BOE-A-2025-26705" in wb
    assert "spain-negative-price-alert/blob/main/docs/tariffs.md" in wb
    assert "illustration" in wb
    assert "https://www.boe.es/diario_boe/txt.php?id=BOE-A-2025-26348" in wb
    assert "https://www.boe.es/diario_boe/txt.php?id=BOE-A-2025-26705" in wb
    assert "https://www.boe.es/buscar/act.php?id=BOE-A-2020-1066" in wb
    assert "https://www.boe.es/eli/es/rd/2023/06/13/446" in wb and "55%" in wb


def test_capture_wording_and_chart_summaries(built):
    html = (built / "index.html").read_text(encoding="utf-8")
    assert "Generation-weighted hourly capture prices (an estimate)" in html
    assert "15-minute periods" in html
    for key in ["scatter", "heatmap", "capture", "profile"]:
        assert (
            f'<details><summary>Data summary (text)</summary><div class="table-wrap" id="summary-{key}">'
            in html
        )
    for name in PAGES:
        assert "actually sell" not in (built / name).read_text(encoding="utf-8"), name


def test_md_to_html_subset():
    md = "# T\n\nA *b* line\nwrapped.\n\n- **one:** `x < y`\n  more\n- [two](https://e.org/a)\n\n## S\n"
    assert site.md_to_html(md) == (
        "<h1>T</h1>\n<p>A <em>b</em> line wrapped.</p>\n<ul>\n"
        "<li><strong>one:</strong> <code>x &lt; y</code> more</li>\n"
        '<li><a href="https://e.org/a">two</a></li>\n</ul>\n<h2>S</h2>'
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_page_kpis_match_python(built, frame):
    """The page's JS, run on the embedded (rounded) data, reproduces transform.kpis."""
    cases = [("2024-10-01", "2026-10-09", 0.0), ("2025-01-15", "2025-06-30", 25.0)]
    out = _node(NODE_KPIS, built, cases)
    for (start, end, threshold), js in zip(cases, out, strict=True):
        df = transform.filter_dates(frame, start, end)
        py = transform.kpis(df)
        low = int((df["price_es"] <= threshold).sum())
        assert js["hours"] == py["hours"]
        assert js["low_hours"] == low
        assert js["pct_low"] * 100 == pytest.approx(low / len(df) * 100, abs=0.1)
        assert js["avg_price"] == pytest.approx(py["avg_price"], abs=0.1)
        assert js["renewables_share"] * 100 == pytest.approx(py["avg_renewables_share"] * 100, abs=0.1)
        assert js["solar_capture"] == pytest.approx(py["solar_capture"], abs=0.1)
        assert js["solar_capture_rate"] * 100 == pytest.approx(py["solar_capture_rate"] * 100, abs=0.1)
    # Full range at threshold 0 is what the page shows on load: it must equal data-expected.
    want = site.expected_kpis(frame)
    js = out[0]
    assert js["low_hours"] == want["low"]
    assert js["avg_price"] == pytest.approx(want["avg"], abs=0.1)
    assert js["renewables_share"] * 100 == pytest.approx(want["ren"], abs=0.1)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_page_charts_match_python(built, frame):
    """Bucket means, heatmap counts and capture prices: full range and a filtered one."""
    cases = [("2024-10-01", "2026-10-09", 0.0), ("2025-01-15", "2025-06-30", 25.0)]
    for (start, end, threshold), js in zip(cases, _node(NODE_CHARTS, built, cases), strict=True):
        _assert_charts_match_python(transform.filter_dates(frame, start, end), threshold, js)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
@pytest.mark.skipif(not PROCESSED.exists(), reason="no data/processed/hourly.parquet")
def test_page_charts_match_python_on_repo_data(tmp_path):
    """The same comparison on the committed hourly table, whose shares do sit near bucket edges."""
    df = load_hourly(PROCESSED)
    site.build(df, tmp_path)
    cases = [(df["date"].min(), df["date"].max(), 0.0), ("2025-03-01", "2026-02-28", 10.0)]
    for (start, end, threshold), js in zip(cases, _node(NODE_CHARTS, tmp_path, cases), strict=True):
        _assert_charts_match_python(transform.filter_dates(df, start, end), threshold, js)
