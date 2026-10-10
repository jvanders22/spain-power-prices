/* Static dashboard logic. The compute functions mirror src/spain_power/transform.py and
   charts.py and run unchanged in Node (tests/test_site.py checks them against Python).

   D is the embedded hourly table, column-wise and sorted by time:
   dates[] (local days), di[] (row -> index into dates), hour[], price[] (EUR/MWh),
   demand[], solar[], wind[], ren[] (MW) and ev[] (1 = grid-event hour, excluded from shares). */
(function (root) {
  "use strict";

  var STEP = 0.1;
  var SHARE_CAP = 1.5;
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  function prepare(raw) {
    var D = Object.assign({}, raw);
    D.ev = new Uint8Array(D.di.length);
    raw.ev.forEach(function (i) {
      D.ev[i] = 1;
    });
    return D;
  }

  // Rows [i0, i1) whose local date is within [start, end] (ISO strings compare correctly).
  function range(D, start, end) {
    var n = D.di.length;
    var i0 = 0;
    var i1 = n;
    while (i0 < n && D.dates[D.di[i0]] < start) i0++;
    while (i1 > i0 && D.dates[D.di[i1 - 1]] > end) i1--;
    return [i0, i1];
  }

  // transform.build_hourly: renewables / demand, capped, undefined for grid-event hours.
  function share(D, i) {
    if (D.ev[i] || !(D.demand[i] > 0)) return NaN;
    return Math.min(D.ren[i] / D.demand[i], SHARE_CAP);
  }

  // transform.kpis, with the app's threshold count in place of the fixed <= 0 one.
  function kpis(D, i0, i1, threshold) {
    var n = i1 - i0;
    var sumP = 0, low = 0, ren = 0, dem = 0, sumPS = 0, sumS = 0;
    for (var i = i0; i < i1; i++) {
      var p = D.price[i];
      sumP += p;
      if (p <= threshold) low++;
      if (!D.ev[i]) {
        ren += D.ren[i];
        dem += D.demand[i];
      }
      sumPS += p * D.solar[i];
      sumS += D.solar[i];
    }
    var avg = sumP / n;
    var capture = sumPS / sumS;
    return {
      hours: n,
      avg_price: avg,
      low_hours: low,
      pct_low: low / n,
      renewables_share: ren / dem,
      solar_capture: capture,
      solar_capture_rate: avg ? capture / avg : NaN,
    };
  }

  // transform.share_buckets: mean price per 10% renewables-share bucket, [left, right).
  function buckets(D, i0, i1) {
    var nb = Math.round(SHARE_CAP / STEP);
    var sum = new Array(nb).fill(0);
    var cnt = new Array(nb).fill(0);
    for (var i = i0; i < i1; i++) {
      var s = share(D, i);
      if (!(s >= 0)) continue;
      var b = Math.floor(s / STEP + 1e-9);
      if (b >= nb) continue;
      sum[b] += D.price[i];
      cnt[b]++;
    }
    var out = [];
    for (var k = 0; k < nb; k++) {
      if (!cnt[k]) continue;
      out.push({
        label: k * 10 + "%-" + (k + 1) * 10 + "%",
        mid: k * STEP + STEP / 2,
        mean: sum[k] / cnt[k],
        count: cnt[k],
      });
    }
    return out;
  }

  function byMonth(D, i0, i1) {
    var months = [];
    var rows = {};
    for (var i = i0; i < i1; i++) {
      var m = D.dates[D.di[i]].slice(0, 7);
      if (!rows[m]) {
        rows[m] = [];
        months.push(m);
      }
      rows[m].push(i);
    }
    return { months: months, rows: rows };
  }

  // transform.negative_hours: month x hour count of hours with price <= threshold.
  function heatmap(D, i0, i1, threshold) {
    var g = byMonth(D, i0, i1);
    var z = g.months.map(function (m) {
      var row = new Array(24).fill(0);
      g.rows[m].forEach(function (i) {
        if (D.price[i] <= threshold) row[D.hour[i]]++;
      });
      return row;
    });
    return { months: g.months, z: z };
  }

  // transform.capture_prices: monthly baseload and generation-weighted solar / wind prices.
  function capture(D, i0, i1) {
    var g = byMonth(D, i0, i1);
    var out = { months: g.months, baseload: [], solar_capture: [], wind_capture: [] };
    g.months.forEach(function (m) {
      var p = 0, ps = 0, s = 0, pw = 0, w = 0;
      g.rows[m].forEach(function (i) {
        p += D.price[i];
        ps += D.price[i] * D.solar[i];
        s += D.solar[i];
        pw += D.price[i] * D.wind[i];
        w += D.wind[i];
      });
      out.baseload.push(p / g.rows[m].length);
      out.solar_capture.push(s ? ps / s : null);
      out.wind_capture.push(w ? pw / w : null);
    });
    return out;
  }

  function ordinal(month) {
    return Number(month.slice(0, 4)) * 12 + Number(month.slice(5, 7)) - 1;
  }

  function monthLabel(ord) {
    return MONTHS[ord % 12] + " " + Math.floor(ord / 12);
  }

  // charts.profile_windows + fig_hourly_profile: average price by hour for each 12-month
  // window counted back from the latest complete month; a partial tail window is dropped
  // when a full one exists.
  function profile(D, i0, i1) {
    if (i1 <= i0) return [];
    var first = ordinal(D.dates[D.di[i0]]);
    var last = ordinal(D.dates[D.di[i1 - 1]]);
    if (first < last) {
      var firstDay = D.di[i1 - 1];
      for (var j = i1 - 1; j >= i0 && ordinal(D.dates[D.di[j]]) === last; j--) firstDay = D.di[j];
      var daysPresent = D.di[i1 - 1] - firstDay + 1;
      var daysInMonth = new Date(Date.UTC(Math.floor(last / 12), (last % 12) + 1, 0)).getUTCDate();
      if (daysPresent < daysInMonth) last -= 1;
    }
    var windows = {};
    var hasFull = false;
    for (var i = i0; i < i1; i++) {
      var m = ordinal(D.dates[D.di[i]]);
      if (m > last) continue;
      var k = Math.floor((last - m) / 12);
      if (!windows[k]) {
        var end = last - 12 * k;
        var start = Math.max(end - 11, first);
        windows[k] = {
          label: monthLabel(start) + "–" + monthLabel(end),
          full: end - start === 11,
          sum: new Array(24).fill(0),
          cnt: new Array(24).fill(0),
        };
        hasFull = hasFull || windows[k].full;
      }
      windows[k].sum[D.hour[i]] += D.price[i];
      windows[k].cnt[D.hour[i]]++;
    }
    return Object.keys(windows)
      .map(function (k) {
        return windows[k];
      })
      .filter(function (w) {
        return w.full || !hasFull;
      })
      .map(function (w) {
        var hours = [];
        var mean = [];
        for (var h = 0; h < 24; h++) {
          if (!w.cnt[h]) continue;
          hours.push(h);
          mean.push(w.sum[h] / w.cnt[h]);
        }
        return { label: w.label, hours: hours, mean: mean };
      })
      .sort(function (a, b) {
        return a.label < b.label ? -1 : a.label > b.label ? 1 : 0; // same order as pandas
      });
  }

  // "Last 12 months": the year ending on the last day of data.
  function lastYearStart(maxDate, minDate) {
    var d = new Date(maxDate + "T00:00:00Z");
    d.setUTCFullYear(d.getUTCFullYear() - 1);
    d.setUTCDate(d.getUTCDate() + 1);
    var s = d.toISOString().slice(0, 10);
    return s < minDate ? minDate : s;
  }

  var api = {
    prepare: prepare,
    range: range,
    share: share,
    kpis: kpis,
    buckets: buckets,
    heatmap: heatmap,
    capture: capture,
    profile: profile,
    lastYearStart: lastYearStart,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.SpainPower = api;
  if (typeof document === "undefined") return;

  // ---- page wiring -------------------------------------------------------------------

  var CONFIG = { responsive: true, displaylogo: false };

  function $(id) {
    return document.getElementById(id);
  }

  function clone(o) {
    return JSON.parse(JSON.stringify(o));
  }

  function num(x, digits) {
    return isFinite(x)
      ? x.toLocaleString("en-GB", { minimumFractionDigits: digits, maximumFractionDigits: digits })
      : "–";
  }

  function pct(x, digits) {
    return isFinite(x) ? num(x * 100, digits) + "%" : "–";
  }

  function hasWebGL() {
    try {
      var c = document.createElement("canvas");
      return !!(c.getContext("webgl") || c.getContext("experimental-webgl"));
    } catch (e) {
      return false;
    }
  }

  function init() {
    var site = JSON.parse($("site-data").textContent);
    var D = prepare(site.data);
    var figs = site.figs;
    var minDate = D.dates[0];
    var maxDate = D.dates[D.dates.length - 1];
    var gl = hasWebGL();

    function layout(name, extra) {
      var l = clone(figs[name].layout);
      l.template = site.template;
      delete l.title; // the section heading carries the title
      l.margin = { l: 60, r: 20, t: 30, b: 50 };
      // 24 hourly tick labels do not fit a phone screen.
      if (window.innerWidth < 600 && l.xaxis && l.xaxis.dtick === 1) l.xaxis.dtick = 3;
      return Object.assign(l, extra || {});
    }

    function drawScatter(i0, i1) {
      var pts = clone(figs.scatter.data[0]);
      if (!gl) pts.type = "scatter";
      var n = i1 - i0;
      pts.x = new Array(n);
      pts.y = new Array(n);
      pts.customdata = new Array(n);
      pts.marker.color = new Array(n);
      for (var i = i0; i < i1; i++) {
        var s = share(D, i);
        pts.x[i - i0] = isFinite(s) ? s : null;
        pts.y[i - i0] = D.price[i];
        pts.marker.color[i - i0] = D.hour[i];
        pts.customdata[i - i0] = [D.dates[D.di[i]], D.hour[i]];
      }
      var traces = [pts];
      var b = buckets(D, i0, i1);
      if (b.length) {
        var line = clone(figs.scatter.data[1]);
        line.x = b.map(function (r) { return r.mid; });
        line.y = b.map(function (r) { return r.mean; });
        line.customdata = b.map(function (r) { return [r.label, r.count]; });
        traces.push(line);
      }
      Plotly.react("chart-scatter", traces, layout("scatter", { height: 480 }), CONFIG);
    }

    function drawHeatmap(i0, i1, threshold) {
      var hm = heatmap(D, i0, i1, threshold);
      var trace = clone(figs.heatmap.data[0]);
      trace.z = hm.z;
      trace.x = Array.from({ length: 24 }, function (_, h) { return h; });
      trace.y = hm.months;
      $("title-heatmap").textContent = "Hours with day-ahead price ≤ " + threshold + " EUR/MWh";
      var height = Math.max(300, 110 + 20 * hm.months.length);
      Plotly.react("chart-heatmap", [trace], layout("heatmap", { height: height }), CONFIG);
    }

    function drawCapture(i0, i1) {
      var c = capture(D, i0, i1);
      var traces = ["baseload", "solar_capture", "wind_capture"].map(function (key, k) {
        var t = clone(figs.capture.data[k]);
        t.x = c.months;
        t.y = c[key];
        return t;
      });
      Plotly.react("chart-capture", traces, layout("capture", { height: 440 }), CONFIG);
    }

    function drawProfile(i0, i1) {
      var traces = profile(D, i0, i1).map(function (w, k) {
        var t = clone(figs.profile.data[0]);
        var color = site.series[k % site.series.length];
        t.name = w.label;
        t.x = w.hours;
        t.y = w.mean;
        t.line.color = color;
        t.marker.color = color;
        t.hovertemplate = w.label + ": %{y:.2f} EUR/MWh<extra></extra>";
        return t;
      });
      Plotly.react("chart-profile", traces, layout("profile", { height: 440 }), CONFIG);
    }

    function update() {
      var start = $("start").value || minDate;
      var end = $("end").value || maxDate;
      var threshold = Number($("threshold").value);
      if (!isFinite(threshold)) threshold = 0;
      var r = range(D, start, end);
      var empty = r[1] <= r[0];
      $("empty").hidden = !empty;
      $("results").hidden = empty;
      if (empty) return;

      var k = kpis(D, r[0], r[1], threshold);
      $("kpi-avg").textContent = num(k.avg_price, 1);
      $("kpi-low-label").textContent = "Hours ≤ " + threshold + " EUR/MWh";
      $("kpi-low").textContent = num(k.low_hours, 0);
      $("kpi-pct").textContent = pct(k.pct_low, 1);
      $("kpi-hours").textContent = num(k.hours, 0);
      $("kpi-ren").textContent = pct(k.renewables_share, 1);
      $("kpi-capture").textContent = num(k.solar_capture, 1);
      $("kpi-rate").textContent = pct(k.solar_capture_rate, 0);
      $("range-note").textContent =
        D.dates[D.di[r[0]]] + " to " + D.dates[D.di[r[1] - 1]] + ", " + num(k.hours, 0) + " hours";

      drawScatter(r[0], r[1]);
      drawHeatmap(r[0], r[1], threshold);
      drawCapture(r[0], r[1]);
      drawProfile(r[0], r[1]);
    }

    function setRange(start, end) {
      $("start").value = start;
      $("end").value = end;
      update();
    }

    // Self-check: on the full range the page must reproduce the build-time Python KPIs.
    function parity() {
      var k = kpis(D, 0, D.di.length, 0);
      var checks = [
        ["kpi-avg", k.avg_price, 0.1],
        ["kpi-low", k.low_hours, 0],
        ["kpi-pct", k.pct_low * 100, 0.1],
        ["kpi-ren", k.renewables_share * 100, 0.1],
        ["kpi-capture", k.solar_capture, 0.1],
        ["kpi-rate", k.solar_capture_rate * 100, 0.1],
      ];
      var ok = checks.every(function (c) {
        return Math.abs(c[1] - Number($(c[0]).dataset.expected)) <= c[2];
      });
      document.body.dataset.parity = ok ? "ok" : "mismatch";
      if (!ok) console.warn("KPI mismatch between page and build-time values");
    }

    ["start", "end", "threshold"].forEach(function (id) {
      $(id).addEventListener("change", update);
    });
    $("btn-all").addEventListener("click", function () {
      setRange(minDate, maxDate);
    });
    $("btn-12m").addEventListener("click", function () {
      setRange(lastYearStart(maxDate, minDate), maxDate);
    });

    parity();
    update();
    document.body.dataset.ready = "1";
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})(typeof globalThis !== "undefined" ? globalThis : this);
