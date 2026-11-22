"""Our own minimalist price chart (Trading 212 / Trade Republic style) using TradingView's open-source
Lightweight Charts (Apache 2.0). The credit link to TradingView is kept, as the licence asks.

Pure HTML builder: points are [(iso_date, close)] computed elsewhere; nothing here fetches data.
"""

import json
from html import escape

LIB_URL = "https://cdn.jsdelivr.net/npm/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"
HEIGHT = 520  # iframe height to request

_TEMPLATE = """<!doctype html>
<meta charset="utf-8">
<style>
  :root { color-scheme: light dark; --fg:#0f172a; --muted:#64748b; --up:#0a9f6e; --down:#e5484d; --chip:#e2e8f0; --chipfg:#0f172a; }
  @media (prefers-color-scheme: dark) { :root { --fg:#f1f5f9; --muted:#94a3b8; --up:#2dd4a0; --down:#ff6b6b; --chip:#1e293b; --chipfg:#f1f5f9; } }
  html, body { margin:0; background:transparent; color:var(--fg); font:14px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  #wrap { padding: 4px 2px 0; }
  #name { color:var(--muted); font-size:14px; }
  #price { font-size:40px; font-weight:650; letter-spacing:-0.02em; margin-top:2px; }
  #chg { font-size:15px; font-weight:550; }
  #date { color:var(--muted); font-size:13px; min-height:18px; }
  #chart { height:300px; margin-top:8px; }
  #ranges { display:flex; gap:8px; justify-content:center; margin-top:10px; }
  #ranges button { border:0; border-radius:999px; padding:6px 14px; font:inherit; font-weight:550; color:var(--muted); background:transparent; cursor:pointer; }
  #ranges button.on { background:var(--chip); color:var(--chipfg); }
  #credit { text-align:right; font-size:11px; color:var(--muted); margin-top:10px; }
  #credit a { color:var(--muted); }
</style>
<div id="wrap">
  <div id="name">__NAME__</div>
  <div id="price">&nbsp;</div>
  <div><span id="chg">&nbsp;</span> <span id="date"></span></div>
  <div id="chart"></div>
  <div id="ranges"></div>
  <div id="credit">Prices: closing values, for information only. Chart by <a href="https://www.tradingview.com/" target="_blank" rel="noopener nofollow">TradingView Lightweight Charts</a></div>
</div>
<script src="__LIB__"></script>
<script>
const DATA = __DATA__;
const RANGES = [["1M", 30], ["1Y", 365], ["5Y", 1825], ["Max", null]];
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const fmt = v => v.toLocaleString("en-US", {style: "currency", currency: "USD"});
const pct = v => (v >= 0 ? "+" : "−") + Math.abs(v).toLocaleString("en-US", {maximumFractionDigits: Math.abs(v) >= 1000 ? 0 : 2, minimumFractionDigits: Math.abs(v) >= 1000 ? 0 : 2}) + "%";
const day = s => new Date(s + "T00:00:00Z").toLocaleDateString("en-US", {year: "numeric", month: "short", day: "numeric", timeZone: "UTC"});

const el = document.getElementById("chart");
const chart = LightweightCharts.createChart(el, {
  width: el.clientWidth, height: el.clientHeight,
  layout: {background: {type: "solid", color: "transparent"}, textColor: css("--muted"), fontFamily: "inherit"},
  grid: {vertLines: {visible: false}, horzLines: {visible: false}},
  rightPriceScale: {visible: false}, leftPriceScale: {visible: false},
  timeScale: {visible: false, borderVisible: false},
  handleScroll: false, handleScale: false,
  crosshair: {mode: 0, vertLine: {labelVisible: false, color: css("--muted"), width: 1, style: 3},
              horzLine: {visible: false, labelVisible: false}},
});
const series = chart.addAreaSeries({lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
                                    crosshairMarkerRadius: 5});
let view = [];

function setHeader(value, date) {
  const first = view[0].value, d = value - first, p = d / first * 100;
  const c = css(d >= 0 ? "--up" : "--down");
  document.getElementById("price").textContent = fmt(value);
  const chg = document.getElementById("chg");
  chg.textContent = (d >= 0 ? "+" : "−") + fmt(Math.abs(d)).replace("-", "") + "  (" + pct(p) + ")";
  chg.style.color = c;
  document.getElementById("date").textContent = date ? day(date) : "";
}

function setRange(label, days) {
  const last = DATA[DATA.length - 1].time;
  let cutoff = "0000-00-00";
  if (days) { const d = new Date(last + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() - days); cutoff = d.toISOString().slice(0, 10); }
  view = DATA.filter(p => p.time >= cutoff);
  if (view.length < 2) view = DATA.slice(-2);
  const up = view[view.length - 1].value >= view[0].value;
  const c = css(up ? "--up" : "--down");
  series.applyOptions({lineColor: c, topColor: c + "33", bottomColor: c + "00"});
  series.setData(view);
  chart.timeScale().fitContent();
  setHeader(view[view.length - 1].value, null);
  document.getElementById("date").textContent = "past " + label.replace("Max", "all time").toLowerCase();
  [...document.querySelectorAll("#ranges button")].forEach(b => b.classList.toggle("on", b.dataset.r === label));
}

RANGES.forEach(([label, days]) => {
  const b = document.createElement("button");
  b.textContent = label; b.dataset.r = label; b.onclick = () => setRange(label, days);
  document.getElementById("ranges").appendChild(b);
});
chart.subscribeCrosshairMove(p => {
  const v = p.time && p.seriesData.get(series);
  if (v) setHeader(v.value, typeof p.time === "string" ? p.time : null);
  else if (view.length) setHeader(view[view.length - 1].value, null), document.getElementById("date").textContent = "";
});
new ResizeObserver(() => chart.applyOptions({width: el.clientWidth})).observe(el);
setRange("1Y", 365);
</script>
"""


DAILY_YEARS = 5  # keep every day for this long; older history is thinned to roughly weekly
OLD_STEP = 5


def thin(points: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Keep daily points for the last DAILY_YEARS years and every OLD_STEP-th point before that (always the last)."""
    if not points:
        return points
    last = points[-1][0]
    cutoff = f"{int(last[:4]) - DAILY_YEARS}{last[4:]}"
    old = [p for p in points if p[0] < cutoff]
    recent = [p for p in points if p[0] >= cutoff]
    return old[::OLD_STEP] + recent


def chart_html(name: str, points: list[tuple[str, float]]) -> str:
    """Self-contained HTML for st.iframe. `name` is escaped; data is JSON with '<' escaped."""
    points = thin(points)
    data = json.dumps([{"time": d, "value": round(v, 4)} for d, v in points]).replace("<", "\\u003c")
    return (_TEMPLATE.replace("__LIB__", LIB_URL).replace("__NAME__", escape(name)).replace("__DATA__", data))
