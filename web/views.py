"""Turns service results into what the templates show. No data access here: only shaping and formatting."""

from dataclasses import dataclass, field, replace
from datetime import date

from tracker import services


class GoStart(Exception):
    """Not signed in and not in the demo: send to the start page."""


@dataclass(frozen=True)
class Viewer:
    email: str | None
    name: str | None
    demo: bool

    @property
    def initial(self) -> str:
        return (self.name or self.email or "?")[:1].upper()


# ---- formatting -----------------------------------------------------------------------------------

def pct(x: float | None, signed: bool = True, digits: int = 1) -> str:
    if x is None:
        return "—"
    s = f"{abs(x):,.{digits}f}%"
    if not signed:
        return ("−" if x < 0 else "") + s
    return ("+" if x >= 0 else "−") + s


def ratio_pct(x: float | None, signed: bool = False) -> str:
    return pct(None if x is None else x * 100, signed=signed)


CURRENCY_PREFIX = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "CNY": "CN¥", "TWD": "NT$", "INR": "₹", "KRW": "₩",
                   "HKD": "HK$", "CAD": "C$", "AUD": "A$"}


def money(x: float | None, ccy: str = "USD") -> str:
    """$1.2B, €32.7B, NT$3.8T; currencies without a common symbol get the code (DKK 309.1B)."""
    if x is None:
        return "—"
    sign = "−" if x < 0 else ""
    pre = CURRENCY_PREFIX.get(ccy, ccy + " ")
    x = abs(x)
    for div, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if x >= div:
            return f"{sign}{pre}{x / div:.1f}{unit}"
    return f"{sign}{pre}{x:,.2f}"


def tone(x: float | None) -> str:
    return "" if x is None else ("up" if x >= 0 else "down")


def nice_date(iso: str | None) -> str:
    if not iso:
        return ""
    d = date.fromisoformat(iso[:10])
    return f"{d:%b} {d.day}, {d.year}"


def short_date(iso: str | None) -> str:
    if not iso:
        return ""
    d = date.fromisoformat(iso[:10])
    return f"{d:%b} {d.day}"


def register_filters(env) -> None:
    env.filters.update(pct=pct, money=money, tone=tone, nice_date=nice_date, short_date=short_date, ratio_pct=ratio_pct)


# ---- source numbering -----------------------------------------------------------------------------

@dataclass
class Refs:
    """Numbers every source once per page, in order of first use. Shown as [1] markers and one list."""
    items: list[dict] = field(default_factory=list)
    _index: dict = field(default_factory=dict)
    labels: dict = field(default_factory=dict)   # url -> nicer label (e.g. the filing's name)

    def number(self, link) -> int:
        label = self.labels.get(link.url) or link.label
        key = link.url or label
        if key not in self._index:
            self.items.append({"n": len(self.items) + 1, "label": label, "url": link.url})
            self._index[key] = len(self.items)
        return self._index[key]

    def numbers(self, links) -> list[int]:
        return sorted({self.number(l) for l in links})


# ---- stock page -----------------------------------------------------------------------------------

TAB_TONES = {"Bull case": "up", "Bear case": "down", "What to watch": "neutral"}


def _exchange(tv_symbol: str) -> str:
    return tv_symbol.split(":")[0] if ":" in tv_symbol else ""


def _since(iso: str | None) -> str:
    if not iso:
        return ""
    d = date.fromisoformat(iso)
    return f"since {d:%b} {d.year}"


def key_facts(stock, facts) -> list[tuple[str, str, str | None]]:
    """(label, value, href) rows for the Key facts card."""
    rows: list[tuple[str, str, str | None]] = []
    if facts:
        if facts.ceo:
            rows.append(("CEO", facts.ceo + (f" · {_since(facts.ceo_since)}" if facts.ceo_since else ""), None))
        if facts.headquarters:
            rows.append(("Headquarters", facts.headquarters + (f", {facts.country}" if facts.country and facts.country != "United States" else ""), None))
        if facts.founded:
            rows.append(("Founded", str(facts.founded), None))
        if facts.employees:
            rows.append(("Employees", f"{facts.employees:,}", None))
    rows.append(("Sector", stock.industry, None))
    rows.append(("Exchange", _exchange(stock.tv_symbol) or "—", None))
    rows.append(("Country", stock.country, None))
    if facts and facts.website:
        host = facts.website.split("//", 1)[-1].split("/", 1)[0].removeprefix("www.")
        rows.append(("Website", host, "https://" + host))
    return rows


def valuation(metrics, price: float | None) -> dict | None:
    """Our own valuation from the latest close and EDGAR figures. Diluted shares = net income / diluted EPS."""
    if metrics is None or not price or not metrics.eps_diluted_ttm or not metrics.net_income_ttm:
        return None
    shares = metrics.net_income_ttm / metrics.eps_diluted_ttm
    mcap = price * shares
    pe = price / metrics.eps_diluted_ttm
    ps = mcap / metrics.revenue_ttm if metrics.revenue_ttm else None
    ev_ebitda = (mcap + (metrics.net_debt or 0)) / metrics.ebitda_ttm if metrics.ebitda_ttm and metrics.ebitda_ttm > 0 else None
    x = lambda v: "—" if v is None or v <= 0 else f"{v:.1f}x"  # noqa: E731
    return {"title": "Valuation", "note": "latest close · SEC filings", "metrics": [
        ("Market value", money(mcap), ""), ("P/E", x(pe), ""), ("Price / sales", x(ps), ""), ("EV / EBITDA", x(ev_ebitda), ""),
        ("Earnings yield", pct(100 / pe if pe > 0 else None, signed=False), ""), ("Last close", f"${price:,.2f}", "")]}


def stock_model(*, stock, perf, profile, financials, note, filings, coverage, facts=None, chart=None) -> dict:
    refs = Refs(labels={f.url: f"{f.label} ({f.form}) · SEC EDGAR" for f in filings})
    if (chart and perf and perf.ranges and chart.ranges and chart.ranges[0].label == "1D"
            and chart.session == perf.as_of):
        # Same 1D number everywhere on the page: the stored daily change, not the intraday estimate.
        # Only for the same session: a stale saved close must not label a newer chart.
        chart = replace(chart, ranges=[replace(chart.ranges[0], pct=perf.ranges[0].pct), *chart.ranges[1:]])
    m: dict = {"refs": refs, "filings": filings, "coverage": coverage, "perf": perf, "chart": chart}

    # Move note first: its sources are the most recent.
    if note:
        m["note"] = {"n": note, "points": [{"text": p.text, "refs": refs.numbers(p.sources)} for p in note.points],
                     "summary_refs": refs.numbers(note.links[:2])}
        for l in note.links:
            refs.number(l)

    m["about"] = None
    m["tabs"] = []
    if profile:
        if profile.about:
            m["about"] = {"sentences": [{"text": p.text, "refs": refs.numbers(p.sources)} for p in profile.about]}
        for title, pts in profile.sections:
            m["tabs"].append({"id": title.split()[0].lower().strip("&"), "label": title, "tone": TAB_TONES.get(title, ""),
                              "points": [{"title": p.title, "text": p.text, "refs": refs.numbers(p.sources)} for p in pts]})
        if profile.what_changed:
            m["tabs"].append({"id": "changed", "label": "What changed", "tone": "neutral",
                              "points": [{"title": "", "text": profile.what_changed, "refs": []}]})
        m["profile_updated"] = profile.updated

    m["facts"] = key_facts(stock, facts)
    m["exchange"] = _exchange(stock.tv_symbol)
    m["country"] = stock.country
    m["facts_source"] = facts

    groups = []
    # A US listing of a foreign company is usually an ADR (one ADR = several or a fraction of a share) priced in
    # dollars while the figures are per ordinary share in the home currency: no price-based ratios for those.
    if not stock.foreign_filer:
        val = valuation(financials.metrics if financials else None, chart.last_close if chart else None)
        if val:
            groups.append(val)
    if financials:
        x = financials.metrics
        c = x.currency
        foreign = stock.foreign_filer or c != "USD"
        span = "TTM" if not foreign else "latest reported year or TTM"
        groups.append({"title": "Growth & profit", "note": f"{span} · SEC filings" + (f" · in {c}" if c != "USD" else ""), "metrics": [
            ("Revenue", money(x.revenue_ttm, c), ""), ("Revenue growth", ratio_pct(x.revenue_growth_yoy, True), tone(x.revenue_growth_yoy)),
            ("Operating margin", ratio_pct(x.operating_margin), ""), ("Net margin", ratio_pct(x.net_margin), ""),
            ("EPS (diluted)" + (", per share" if foreign else ""), "—" if x.eps_diluted_ttm is None else money(x.eps_diluted_ttm, c), ""),
            ("Net income", money(x.net_income_ttm, c), "")]})
        nd = x.net_debt_to_ebitda
        groups.append({"title": "Balance sheet", "note": "SEC filings", "metrics": [
            ("Net debt", money(x.net_debt, c), ""),
            ("Net debt / EBITDA", "—" if nd is None else (f"{nd:.1f}x" + (" (net cash)" if nd < 0 else "")), "")]})
        m["financials_as_of"] = x.as_of.isoformat() if x.as_of else None
    if perf and perf.risk:
        r = perf.risk
        one_year = next((v.pct for v in perf.ranges if v.label == "1Y"), None)
        groups.append({"title": "Risk", "note": "last 12 months", "metrics": [
            ("1-year return", pct(one_year), tone(one_year)), ("Volatility", pct(r.volatility_pct, signed=False), ""),
            ("Beta vs S&P 500", "—" if r.beta is None else f"{r.beta:.2f}", ""),
            ("Largest drop", pct(r.max_drawdown_pct), "down"),
            ("Best day", pct(r.best_day_pct), "up"), ("Worst day", pct(r.worst_day_pct), "down")]})
    m["groups"] = groups
    if facts:
        refs.number(services.SourceLink("Key facts · Wikidata", facts.wikidata_url))
        if stock.logo:
            refs.number(services.SourceLink("Logo · Wikimedia Commons", stock.logo.split("?", 1)[0].replace("Special:FilePath/", "File:")))
    return m


# ---- portfolio ------------------------------------------------------------------------------------

def exposure_breakdown(stocks) -> dict[str, list[tuple[str, int]]]:
    from collections import Counter

    return {
        label: sorted(Counter(getattr(stock, attr) for stock in stocks).items(), key=lambda pair: (-pair[1], pair[0]))
        for label, attr in (("Industry", "industry"), ("Region", "region"))
    }


def latest_note(pairs):
    """pairs = [(stock, MoveNote)]: the newest note, biggest move first on the same day."""
    return max(pairs, key=lambda p: (p[1].date, abs(p[1].return_pct)), default=(None, None))


def outlet_names(domains: set[str], outlets) -> str:
    names = [o.name for o in outlets if o.domain in domains]
    return ", ".join(names) if names else "all outlets"


# ---- settings, setup, news ------------------------------------------------------------------------------

MIN_START_STOCKS = 3


def prefs_from_form(form, *, email_ready: bool, alerts_only: bool = False) -> dict:
    """Checkboxes are absent when off. Display settings are left alone on the setup page's alerts step."""
    out = {"stock_alerts": form.get("stock_alerts") == "1", "market_alerts": form.get("market_alerts") == "1",
           "email_alerts": email_ready and form.get("email_alerts") == "1"}
    try:
        out["alert_threshold_pct"] = float(form.get("alert_threshold_pct") or 5.0)
    except ValueError:
        out["alert_threshold_pct"] = 5.0
    out["digest"] = str(form.get("digest") or "weekly")
    if not alerts_only:
        out["home"] = str(form.get("home") or "portfolio")
        out["perf_basis"] = str(form.get("perf_basis") or "start")
    return out


def news_model(p) -> dict:
    return {"market": p.market, "moves": p.moves, "live": p.live, "searches_left": p.searches_left,
            "outlets": p.outlets, "weekly_brief": p.weekly_brief,
            "closing_news": p.closing_news, "stock_closing_news": p.stock_closing_news}
