"""Turns service results into what the templates show. No data access here: only shaping and formatting."""

from dataclasses import dataclass, field
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
    s = f"{abs(x):.{digits}f}%"
    if not signed:
        return ("−" if x < 0 else "") + s
    return ("+" if x >= 0 else "−") + s


def ratio_pct(x: float | None, signed: bool = False) -> str:
    return pct(None if x is None else x * 100, signed=signed)


def money(x: float | None) -> str:
    if x is None:
        return "—"
    sign = "−" if x < 0 else ""
    x = abs(x)
    for div, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if x >= div:
            return f"{sign}${x / div:.1f}{unit}"
    return f"{sign}${x:,.2f}"


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

TAB_TONES = {"Strategy and trajectory": "", "Bull case": "up", "Bear case": "down"}
TAB_LABELS = {"Strategy and trajectory": "Strategy & outlook", "Bull case": "Bull case", "Bear case": "Bear case"}


def _exchange(tv_symbol: str) -> str:
    return tv_symbol.split(":")[0] if ":" in tv_symbol else ""


def stock_model(*, stock, perf, profile, financials, note, filings, coverage) -> dict:
    refs = Refs(labels={f.url: f"{f.label} ({f.form}) · SEC EDGAR" for f in filings})
    m: dict = {"refs": refs, "filings": filings, "coverage": coverage, "perf": perf}

    # Move note first: its sources are the most recent.
    if note:
        m["note"] = {"n": note, "points": [{"text": p.text, "refs": refs.numbers(p.sources)} for p in note.points],
                     "summary_refs": refs.numbers(note.links[:2])}
        for l in note.links:
            refs.number(l)

    m["about"] = None
    m["tabs"] = []
    if profile:
        sections = dict(profile.sections)
        overview = sections.get("Overview and sector", [])
        if overview:
            m["about"] = {"sentences": [{"text": p.text, "refs": refs.numbers(p.sources)} for p in overview]}
        for title in ("Strategy and trajectory", "Bull case", "Bear case"):
            pts = sections.get(title, [])
            if pts:
                m["tabs"].append({"id": title.split()[0].lower(), "label": TAB_LABELS[title], "tone": TAB_TONES[title],
                                  "points": [{"text": p.text, "refs": refs.numbers(p.sources)} for p in pts]})
        if profile.what_changed:
            m["tabs"].append({"id": "changed", "label": "What changed", "tone": "neutral",
                              "points": [{"text": profile.what_changed, "refs": []}]})
        m["profile_updated"] = profile.updated

    m["facts"] = [("Sector", stock.industry), ("Exchange", _exchange(stock.tv_symbol) or "—"), ("Country", "United States")]
    if stock.rank:
        m["facts"].append(("Size rank", f"#{stock.rank} in the US by market value"))

    groups = []
    if financials:
        x = financials.metrics
        groups.append({"title": "Growth & profit", "note": "TTM · SEC filings", "metrics": [
            ("Revenue", money(x.revenue_ttm), ""), ("Revenue growth", ratio_pct(x.revenue_growth_yoy, True), tone(x.revenue_growth_yoy)),
            ("Operating margin", ratio_pct(x.operating_margin), ""), ("Net margin", ratio_pct(x.net_margin), ""),
            ("EPS (diluted)", "—" if x.eps_diluted_ttm is None else f"${x.eps_diluted_ttm:.2f}", ""),
            ("Net income", money(x.net_income_ttm), "")]})
        nd = x.net_debt_to_ebitda
        groups.append({"title": "Balance sheet", "note": "SEC filings", "metrics": [
            ("Net debt", money(x.net_debt), ""),
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
    return m


# ---- portfolio ------------------------------------------------------------------------------------

def stock_card(stock, move: tuple[str, float] | None) -> dict:
    return {"s": stock, "date": move[0] if move else None, "day": move[1] if move else None}


def day_summary(cards: list[dict]) -> dict | None:
    days = [c for c in cards if c["day"] is not None]
    if not days:
        return None
    last = max(c["date"] for c in days)
    today = [c for c in days if c["date"] == last]
    return {"date": last, "up": sum(c["day"] >= 0 for c in today), "down": sum(c["day"] < 0 for c in today),
            "avg": sum(c["day"] for c in today) / len(today), "n": len(today)}


def latest_note(pairs):
    """pairs = [(stock, MoveNote)]: the newest note, biggest move first on the same day."""
    return max(pairs, key=lambda p: (p[1].date, abs(p[1].return_pct)), default=(None, None))


def outlet_names(domains: set[str], outlets) -> str:
    names = [o.name for o in outlets if o.domain in domains]
    return ", ".join(names) if names else "all outlets"
