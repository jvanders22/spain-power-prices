"""Static site: the dashboard, the case study and the wholesale-vs-bill explainer as plain files.

``build`` is deterministic (same hourly table in, byte-identical files out) and the result
needs no network at view time: plotly.js is copied from the installed plotly package and
there are no external fonts, scripts or styles.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs

from . import case_study, charts, tariff20td, transform

STATIC = Path(__file__).parent / "static"
REPO_URL = "https://github.com/jvanders22/spain-power-prices"
COMPANION_URL = case_study.COMPANION_URL
ATTRIBUTION = (
    "Data: OMIE (omie.es) and Red Eléctrica (ree.es). Not affiliated. "
    "Wholesale day-ahead prices, not retail bills."
)
NAV = [
    ("index.html", "Dashboard"),
    ("case-study.html", "Case study"),
    ("wholesale-vs-bill.html", "Wholesale ≠ your bill"),
]
BOE = "https://www.boe.es/diario_boe/txt.php?id="
CIRCULAR_3_2020 = "https://www.boe.es/buscar/act.php?id=BOE-A-2020-1066"
RD_446_2023 = "https://www.boe.es/eli/es/rd/2023/06/13/446"

CSS = """
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
color:#1b1f24;background:#f6f7f9;line-height:1.55}
a{color:#1d5fb4}
header{background:#fff;border-bottom:1px solid #e3e6ea}
nav{max-width:1100px;margin:0 auto;padding:10px 16px;display:flex;flex-wrap:wrap;gap:4px 18px;
align-items:center}
nav .brand{font-weight:700;margin-right:auto;color:#1b1f24;text-decoration:none}
nav a{text-decoration:none;padding:4px 0}
nav a[aria-current]{color:#1b1f24;font-weight:600;border-bottom:2px solid #2a78d6}
main{max-width:1100px;margin:0 auto;padding:8px 16px 32px}
main.prose{max-width:760px}
h1{font-size:1.7rem;line-height:1.25;margin:20px 0 6px}
h2{font-size:1.15rem;margin:0 0 4px}
.prose h2{font-size:1.25rem;margin:28px 0 8px}
.muted{color:#5b6470;font-size:.92rem}
.card{background:#fff;border:1px solid #e3e6ea;border-radius:8px;padding:14px 16px;margin:14px 0}
.controls{display:flex;flex-wrap:wrap;gap:12px 18px;align-items:flex-end}
.controls label{display:flex;flex-direction:column;font-size:.85rem;color:#5b6470;gap:3px}
input,button{font:inherit;padding:6px 10px;border:1px solid #c5cad1;border-radius:6px;background:#fff;
color:inherit}
input[type=number]{width:7.5em}
button{cursor:pointer}
button:hover{background:#eef3fa}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:14px 0}
.kpi{background:#fff;border:1px solid #e3e6ea;border-radius:8px;padding:12px 14px}
.kpi .label{font-size:.85rem;color:#5b6470}
.kpi .value{font-size:1.7rem;font-weight:650;line-height:1.3}
.kpi .sub{font-size:.8rem;color:#5b6470}
.chart{width:100%;min-height:300px}
.table-wrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.95rem;margin:10px 0}
th,td{padding:6px 10px;border-bottom:1px solid #e3e6ea;text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th{font-weight:600;background:#f6f7f9}
code{background:#eef0f3;padding:1px 4px;border-radius:4px;font-size:.92em}
details{margin-top:8px;font-size:.92rem}
summary{cursor:pointer;color:#1d5fb4}
details table{width:auto;min-width:50%;font-size:.88rem}
.note{border-left:4px solid #eda100;background:#fff8e6;padding:10px 14px;border-radius:0 6px 6px 0}
footer{max-width:1100px;margin:0 auto;padding:16px;color:#5b6470;font-size:.88rem;
border-top:1px solid #e3e6ea}
@media (max-width:600px){h1{font-size:1.35rem}.kpi .value{font-size:1.4rem}main{padding:8px 10px 24px}
.card{padding:10px}}
"""


# ---- data ------------------------------------------------------------------------------


def _day(date: str) -> str:
    ts = pd.Timestamp(date)
    return f"{ts.day} {ts:%b %Y}"


def payload(df: pd.DataFrame) -> dict:
    """The hourly columns the page needs, column-wise and rounded (prices 4 dp, MW to 1 MW).

    Prices keep 4 decimals because hourly averages of 15-minute prices have up to four, and
    the count of hours at or below a threshold must not change through rounding.

    ``share`` is the renewables share from ``transform.build_hourly`` (4 dp, ``None`` where it
    is undefined) and ``bucket`` its ``transform.share_bucket`` index (-1 for none). The
    bucket is taken from the unrounded share, so the page's bucket means cannot drift from
    ``transform.share_buckets`` when a share sits next to a bucket edge.
    """
    dates = sorted(df["date"].astype(str).unique())
    index = {d: i for i, d in enumerate(dates)}

    def mw(col: str) -> list[int]:
        return [int(v) for v in df[col].round()]

    return {
        "dates": dates,
        "di": [index[d] for d in df["date"].astype(str)],
        "hour": [int(h) for h in df["hour"]],
        "price": [float(p) for p in df["price_es"].round(4)],
        "demand": mw("demand"),
        "solar": mw("solar"),
        "wind": mw("wind"),
        "ren": mw("renewables"),
        "share": [None if pd.isna(s) else float(s) for s in df["renewables_share"].round(4)],
        "bucket": [int(b) for b in transform.share_bucket(df["renewables_share"]).cat.codes],
        "ev": [i for i, e in enumerate(df["grid_event"]) if e],
    }


def expected_kpis(df: pd.DataFrame) -> dict[str, float]:
    """Full-range, threshold-0 KPIs from ``transform.kpis``, in the units the page shows."""
    k = transform.kpis(df)
    return {
        "avg": k["avg_price"],
        "low": k["zero_or_negative_hours"],
        "pct": k["pct_zero_or_negative"] * 100,
        "ren": k["avg_renewables_share"] * 100,
        "capture": k["solar_capture"],
        "rate": k["solar_capture_rate"] * 100,
        "hours": k["hours"],
    }


_ARRAYS = ("x", "y", "z", "customdata")


def _spec(fig) -> dict:
    """A figure's layout and trace styling without its data; the page fills the arrays in."""
    spec = json.loads(fig.to_json())
    spec["layout"].pop("template", None)
    for trace in spec["data"]:
        for key in _ARRAYS:
            trace.pop(key, None)
        marker = trace.get("marker", {})
        if not isinstance(marker.get("color", ""), str):
            marker.pop("color")
    return spec


def fig_specs(df: pd.DataFrame) -> dict:
    """Styling of the four dashboard charts, taken from the shared builders in ``charts``."""
    return {
        "scatter": _spec(charts.fig_price_vs_renewables(df)),
        "heatmap": _spec(charts.fig_negative_heatmap(df)),
        "capture": _spec(charts.fig_capture_prices(df)),
        "profile": _spec(charts.fig_hourly_profile(df)),
    }


def _template() -> dict:
    return json.loads(go.Figure(layout={"template": charts.TEMPLATE}).to_json())["layout"]["template"]


def _json(obj) -> str:
    """Compact JSON that is safe inside a <script> element."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False, allow_nan=False).replace("</", "<\\/")


# ---- markdown --------------------------------------------------------------------------


def _inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', text)


def md_to_html(md: str) -> str:
    """Convert the small markdown subset the case study uses.

    Handles ``#`` headings, paragraphs, ``-`` lists (with indented continuation lines),
    inline code, bold, emphasis and links. Not a general markdown parser.
    """
    out: list[str] = []
    para: list[str] = []
    items: list[str] = []

    def flush() -> None:
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()
        if items:
            out.append("<ul>\n" + "\n".join(f"<li>{_inline(i)}</li>" for i in items) + "\n</ul>")
            items.clear()

    for line in md.splitlines():
        heading = re.match(r"(#{1,6}) (.+)", line)
        if not line.strip():
            flush()
        elif heading:
            flush()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
        elif line.startswith("- "):
            if para:
                flush()
            items.append(line[2:].strip())
        elif items and line.startswith("  "):
            items[-1] += " " + line.strip()
        else:
            if items:
                flush()
            para.append(line.strip())
    flush()
    return "\n".join(out)


# ---- pages -----------------------------------------------------------------------------


def _page(
    title: str, active: str, body: str, data_through: str, *, prose: bool = False, tail: str = ""
) -> str:
    current = ' aria-current="page"'
    links = "".join(
        f'<a href="{href}"{current if href == active else ""}>{html.escape(label)}</a>' for href, label in NAV
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} · Spanish power prices vs renewables</title>
<meta name="description" content="Spanish day-ahead power prices vs renewables: OMIE prices and \
REE generation, hourly.">
<link rel="icon" href="data:,">
<style>{CSS}</style>
</head>
<body>
<header><nav aria-label="Main">
<a class="brand" href="index.html">Spanish power prices</a>
{links}<a href="{REPO_URL}">GitHub repo</a>
</nav></header>
<main{' class="prose"' if prose else ""}>
{body}
</main>
<footer>
<p>Data through {_day(data_through)}. {ATTRIBUTION}</p>
</footer>
{tail}</body>
</html>
"""


def _kpi(key: str, label: str, value: str, expected: float, sub: str = "", label_id: str = "") -> str:
    lid = f' id="{label_id}"' if label_id else ""
    return (
        f'<div class="kpi"><div class="label"{lid}>{label}</div>'
        f'<div class="value" id="kpi-{key}" data-expected="{expected:.4f}">{value}</div>'
        f'<div class="sub">{sub}</div></div>'
    )


def _chart(key: str, title: str, text: str, alt: str) -> str:
    return (
        f'<section class="card"><h2 id="title-{key}">{html.escape(title)}</h2>'
        f'<p class="muted">{text}</p>'
        f'<div class="chart" id="chart-{key}" role="img" aria-label="{html.escape(alt)}"></div>'
        "<details><summary>Data summary (text)</summary>"
        f'<div class="table-wrap" id="summary-{key}"></div></details></section>'
    )


def index_html(df: pd.DataFrame) -> str:
    d_min, d_max = df["date"].min(), df["date"].max()
    e = expected_kpis(df)
    specs = fig_specs(df)
    titles = {k: s["layout"]["title"]["text"] for k, s in specs.items()}
    blob = {"data": payload(df), "figs": specs, "template": _template(), "series": charts.SERIES}
    kpis = "".join(
        [
            _kpi("avg", "Avg price (€/MWh)", f"{e['avg']:.1f}", e["avg"]),
            _kpi(
                "low",
                "Hours ≤ 0 EUR/MWh",
                f"{e['low']:,}",
                e["low"],
                f'<span id="kpi-pct" data-expected="{e["pct"]:.4f}">{e["pct"]:.1f}%</span> of '
                f'<span id="kpi-hours" data-expected="{e["hours"]}">{e["hours"]:,}</span> hours',
                label_id="kpi-low-label",
            ),
            _kpi("ren", "Renewables share", f"{e['ren']:.1f}%", e["ren"], "of demand, energy-weighted"),
            _kpi(
                "capture",
                "Solar capture (€/MWh)",
                f"{e['capture']:.1f}",
                e["capture"],
                "generation-weighted, hourly (estimate)",
            ),
            _kpi("rate", "Solar capture rate", f"{e['rate']:.0f}%", e["rate"], "capture ÷ average price"),
        ]
    )
    body = f"""<h1>Spanish power prices vs renewables</h1>
<p class="muted">OMIE day-ahead marginal price (Spain) and REE peninsular generation mix, hourly,
{_day(d_min)} – {_day(d_max)}. Data through <strong>{_day(d_max)}</strong>. These are wholesale
prices: <a href="wholesale-vs-bill.html">not what a household pays</a>.</p>

<section class="card" aria-label="Filters">
<div class="controls">
<label>From <input type="date" id="start" value="{d_min}" min="{d_min}" max="{d_max}"></label>
<label>To <input type="date" id="end" value="{d_max}" min="{d_min}" max="{d_max}"></label>
<button type="button" id="btn-12m">Last 12 months</button>
<button type="button" id="btn-all">All</button>
<label>Zero/negative threshold (EUR/MWh)
<input type="number" id="threshold" value="0" step="1"></label>
</div>
<p class="muted" id="range-note" style="margin:10px 0 0">{d_min} to {d_max}, {e["hours"]:,} hours</p>
</section>

<noscript><p class="note">The filters and charts need JavaScript. The numbers below cover the
full date range.</p></noscript>
<p class="note" id="empty" hidden>No hourly data in the selected date range.</p>

<div id="results">
<div class="kpis" aria-live="polite">{kpis}</div>
{
        _chart(
            "scatter",
            titles["scatter"],
            "Each dot is one hour, coloured by hour of day. The black line is the average price per "
            "10-point bucket of renewables share.",
            "Scatter plot of hourly day-ahead price against renewables share of demand, with the "
            "mean price per 10-point share bucket. The bucket means are in the data summary below.",
        )
    }
{
        _chart(
            "heatmap",
            titles["heatmap"],
            "Count of hours at or below the threshold, by month and hour of day (Europe/Madrid).",
            "Heatmap of the number of hours at or below the price threshold, by month and hour of "
            "day. The five highest cells are in the data summary below.",
        )
    }
{
        _chart(
            "capture",
            titles["capture"],
            "Generation-weighted hourly capture prices (an estimate): capture price = "
            "Σ(price × generation) / Σ(generation), beside the simple average (baseload) price. "
            "Since 1 Oct 2025 the market clears in 15-minute periods, so price and output moves "
            "within an hour are averaged away.",
            "Line chart of the monthly baseload price and the generation-weighted solar and wind "
            "capture prices. The monthly values are in the data summary below.",
        )
    }
{
        _chart(
            "profile",
            titles["profile"],
            "One line per 12-month window, counted back from the latest complete month in the range.",
            "Line chart of the average day-ahead price by hour of day for each 12-month window. "
            "The hourly values are in the data summary below.",
        )
    }
</div>

<section class="card">
<h2>Data</h2>
<p><a href="data/hourly.csv" download>Download the hourly data (CSV)</a>: {len(df):,} rows, one per
hour, with prices, demand, generation by technology and the derived shares. Method and sources
are in the <a href="case-study.html">case study</a> and the <a href="{REPO_URL}">repo</a>.</p>
</section>"""
    tail = (
        f'<script id="site-data" type="application/json">{_json(blob)}</script>\n'
        '<script src="assets/plotly.min.js"></script>\n<script src="assets/app.js"></script>\n'
    )
    return _page("Dashboard", "index.html", body, d_max, tail=tail)


def case_study_html(df: pd.DataFrame) -> str:
    body = md_to_html(case_study.render(df))
    body += (
        '\n<p class="muted">The charts behind these numbers are on the '
        '<a href="index.html">dashboard</a>; the code is in the '
        f'<a href="{REPO_URL}">repo</a>.</p>'
    )
    return _page("Case study", "case-study.html", body, df["date"].max(), prose=True)


def wholesale_html(df: pd.DataFrame) -> str:
    d_min, d_max = df["date"].min(), df["date"].max()
    s = tariff20td.summary(df)
    terms = tariff20td.tolls_and_charges()
    p1_morning = df[(tariff20td.periods(df) == "P1") & df["hour"].between(10, 13)]["price_es"].mean()
    low_total = int(s["low_hours"].sum())
    hours = {"P1": "10–14, 18–22", "P2": "8–10, 14–18, 22–24", "P3": "0–8, weekends, holidays"}

    def name(p: str) -> str:
        return f"{p} {tariff20td.PERIODS[p]}"

    terms_rows = "".join(
        f"<tr><td>{name(p)}</td><td>{hours[p]}</td><td>{tariff20td.PEAJES[p]:.6f}</td>"
        f"<td>{tariff20td.CARGOS[p]:.6f}</td><td>{terms[p]:.3f}</td></tr>"
        for p in terms
    )
    data_rows = "".join(
        f"<tr><td>{name(p)}</td><td>{r.hours_share:.1%}</td><td>{r.avg_price:.1f}</td>"
        f"<td>{r.tolls_and_charges:.1f}</td><td>{r.avg_price + r.tolls_and_charges:.1f}</td>"
        f"<td>{r.low_hours:,} ({r.low_share:.0%})</td></tr>"
        for p, r in s.iterrows()
    )
    body = f"""<h1>Wholesale is not your bill</h1>
<p>The dashboard shows the <strong>OMIE day-ahead price</strong>: the wholesale price of energy at
the power-station busbar. A zero-price hour there does not mean free electricity at home. This
page puts a rough size on the difference for the 2.0TD tariff (households and small businesses
up to 15 kW).</p>
<p class="note"><strong>Estimate, for illustration only.</strong> It is not a bill calculator and
not advice. The full 2.0TD/3.0TD calculator is in the companion repo:
<a href="{COMPANION_URL}/blob/main/docs/tariffs.md">spain-negative-price-alert, docs/tariffs.md</a>.</p>

<h2>What a 2.0TD bill adds to the wholesale price</h2>
<ul>
<li><strong>Losses and system services.</strong> Energy lost between the busbar and the meter, plus
balancing and other system costs.</li>
<li><strong>Peajes</strong> (network tolls, set by CNMC) and <strong>cargos</strong> (system
charges, set by MITECO), per kWh and different in each time-of-use period.</li>
<li><strong>Taxes.</strong> The electricity tax (IEE), then VAT (IVA) on top of everything.</li>
<li><strong>A fixed power term</strong> per contracted kW, which does not depend on consumption
at all.</li>
</ul>
<p>How much the OMIE price moves a bill depends on the contract. Indexed free-market contracts
(a market pass-through) follow it most directly. The regulated PVPC tariff follows it only partly
in 2026: <a href="{RD_446_2023}">Real Decreto 446/2023</a> indexes 55% of the PVPC energy cost to
a basket of futures prices in 2026, and only the rest follows the spot market. A fixed-price
contract does not follow it.</p>

<h2>Regulated energy terms, 2026</h2>
<div class="table-wrap"><table>
<thead><tr><th>Period</th><th>Hours (working days)</th><th>Peajes (€/kWh)</th><th>Cargos (€/kWh)</th>
<th>Together (€/MWh)</th></tr></thead>
<tbody>{terms_rows}</tbody>
</table></div>
<p class="muted">Peajes: CNMC Resolución of 18 Dec 2025
(<a href="{BOE}BOE-A-2025-26348">BOE-A-2025-26348</a>). Cargos: Orden TED/1524/2025
(<a href="{BOE}BOE-A-2025-26705">BOE-A-2025-26705</a>), segment 1. Periods:
<a href="{CIRCULAR_3_2020}">CNMC Circular 3/2020</a>, peninsular calendar; Saturdays, Sundays,
6 January and fixed-date national holidays are valle all day.</p>

<h2>Applied to the hourly data</h2>
<p>Each hour from {_day(d_min)} to {_day(d_max)} is assigned its 2.0TD period, then the 2026
terms are set beside the average OMIE price of that period.</p>
<div class="table-wrap"><table>
<thead><tr><th>Period</th><th>Share of hours</th><th>Avg OMIE price (€/MWh)</th>
<th>Peajes + cargos (€/MWh)</th><th>Sum (€/MWh)</th><th>Hours ≤ 0 €/MWh</th></tr></thead>
<tbody>{data_rows}</tbody>
</table></div>
<ul>
<li>On working days from 10:00 to 13:59, the first punta block and the heart of the solar day, the
OMIE price averaged <strong>{p1_morning:.1f} €/MWh</strong>. The punta peajes and cargos alone are
<strong>{terms["P1"]:.2f} €/MWh</strong>, {terms["P1"] / p1_morning:.1f} times the energy itself.</li>
<li>Of the {low_total:,} hours at or below 0 €/MWh, <strong>{s.loc["P1", "low_share"]:.0%}</strong>
fell in punta, {s.loc["P2", "low_share"]:.0%} in llano and {s.loc["P3", "low_share"]:.0%} in valle
(which includes every weekend hour).</li>
<li>So in a zero-price punta hour a 2.0TD customer on an indexed contract still carries
{terms["P1"]:.2f} €/MWh ({terms["P1"] / 10:.2f} c/kWh) of peajes and cargos, before losses, system
services and taxes. In valle the same terms are {terms["P3"]:.2f} €/MWh.</li>
</ul>
<p class="muted">Limits: the "Sum" column leaves out losses, system services, taxes and the power
term, so it is a floor under the energy part of an indexed bill, not the bill. The 2026 terms are
applied to the whole period although earlier years had different values. Movable, regional and
local holidays are treated as working days, as the tariff calendar does.</p>"""
    return _page("Wholesale ≠ your bill", "wholesale-vs-bill.html", body, d_max, prose=True)


def build(df: pd.DataFrame, out: Path) -> list[Path]:
    """Write the site under ``out`` and return the files written."""
    table = df.drop(columns=["ts"], errors="ignore")
    floats = table.select_dtypes("float").columns
    table = table.assign(**{c: table[c].round(4) for c in floats})
    files = {
        "index.html": index_html(df),
        "case-study.html": case_study_html(df),
        "wholesale-vs-bill.html": wholesale_html(df),
        "assets/plotly.min.js": get_plotlyjs(),
        "assets/app.js": (STATIC / "app.js").read_text(encoding="utf-8"),
        "data/hourly.csv": table.to_csv(index=False),
    }
    written = []
    for name, text in files.items():
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(path)
    return written
