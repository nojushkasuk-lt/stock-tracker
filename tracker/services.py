"""The only tracker module app.py imports. Display code asks for data here; it never touches the DB or an API.

Demo mode is read-only (rule 7): everything in this file reads, nothing writes.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from tracker.analysis.metrics import AnnualPoint, Metrics, annual_history, compute_metrics
from tracker.data.charts import get_chart_series
from tracker.db import session_scope
from tracker import config
from tracker.data import news
from tracker.ai import outputs
from tracker.models import Filing, Fundamental, ListingSeen, Universe
from ui.tradingview import tv_symbol


@dataclass(frozen=True)
class Stock:
    ticker: str
    name: str
    industry: str
    rank: int | None
    tv_symbol: str  # e.g. NASDAQ:AAPL


def _query():
    return select(Universe, ListingSeen.exchange).join(
        ListingSeen, ListingSeen.ticker == Universe.ticker, isouter=True
    )


def _to_stock(u: Universe, exchange: str | None) -> Stock:
    return Stock(u.ticker, u.name, u.industry, u.market_cap_rank, tv_symbol(u.ticker, exchange))


def get_demo_stocks() -> list[Stock]:
    """The demo stocks (current top 20), largest first. Empty if the database is not set up yet."""
    try:
        with session_scope() as s:
            rows = s.execute(
                _query().where(Universe.is_demo, Universe.active).order_by(Universe.market_cap_rank)
            ).all()
            return [_to_stock(u, ex) for u, ex in rows]
    except OperationalError:
        return []


def get_stock(ticker: str) -> Stock | None:
    try:
        with session_scope() as s:
            row = s.execute(_query().where(Universe.ticker == ticker.upper())).first()
            return _to_stock(*row) if row else None
    except OperationalError:
        return None


@dataclass(frozen=True)
class ChartData:
    daily: list[tuple[str, float]]  # (YYYY-MM-DD, close)
    intraday: dict[str, list[tuple[int, float]]]  # "1D"/"1W" -> (epoch seconds, close); may be empty


def get_chart_data(ticker: str) -> ChartData | None:
    """Data for the custom chart, or None when it is switched off (then use the TradingView widgets)."""
    series = get_chart_series(ticker.upper())
    if series is None:
        return None
    return ChartData([(d.isoformat(), v) for d, v in series.points], series.intraday)


@dataclass(frozen=True)
class Financials:
    metrics: Metrics
    history: list[AnnualPoint]  # full fiscal years, oldest first (revenue and margin chart)


def get_financials(ticker: str) -> Financials | None:
    """Ratios and yearly history computed from stored SEC figures, or None if the ticker is unknown."""
    try:
        with session_scope() as s:
            u = s.get(Universe, ticker.upper())
            if u is None:
                return None
            rows = list(s.scalars(select(Fundamental).where(Fundamental.ticker == u.ticker)))
            return Financials(compute_metrics(rows, u.industry), annual_history(rows))
    except OperationalError:
        return None


@dataclass(frozen=True)
class FilingLink:
    form: str
    filed: str  # YYYY-MM-DD
    url: str
    label: str


_FORM_LABEL = {"10-K": "Annual report", "10-Q": "Quarterly report", "8-K": "Current report"}


def get_recent_filings(ticker: str, limit: int = 6) -> list[FilingLink]:
    """Latest SEC filings we have detected for the stock (public domain, links to sec.gov)."""
    try:
        with session_scope() as s:
            rows = s.scalars(select(Filing).where(Filing.ticker == ticker.upper())
                             .order_by(Filing.filed_at.desc()).limit(limit))
            out = []
            for f in rows:
                label = _FORM_LABEL.get(f.form, f.form)
                if f.form == "8-K" and "2.02" in (f.items or ""):
                    label = "Earnings release"
                out.append(FilingLink(f.form, f.filed_at.date().isoformat(), f.url, label))
            return out
    except OperationalError:
        return []


def get_outlets() -> list[news.Outlet]:
    return news.load_outlets()


def coverage_enabled() -> bool:
    """Live searches are off in demo mode (rule 7). Until sign-in exists (Day 5) they run only in local dev."""
    return config.APP_ENV == "local" and bool(config.BRAVE_SEARCH_API_KEY)


@dataclass(frozen=True)
class Coverage:
    links: list[news.NewsLink]
    message: str | None = None  # shown instead of / above the links


def get_coverage(ticker: str, domains: set[str] | None = None) -> Coverage:
    """Live, outlet-filtered links for one stock. Results stay in memory; only the search count is stored."""
    if not coverage_enabled():
        return Coverage([], "Live coverage search is available to signed-in users.")
    stock = get_stock(ticker)
    if stock is None:
        return Coverage([], "Unknown stock.")
    try:
        with session_scope() as s:
            results = news.cached_search(s, news.BraveNews(), news.coverage_query(stock.name, stock.ticker, domains))
    except news.SearchCapReached:
        return Coverage([], "The monthly search limit has been reached. Coverage will be back next month.")
    except Exception:
        return Coverage([], "News search is unavailable right now.")
    links = news.coverage_links(results, news.load_outlets(), domains)
    return Coverage(links, None if links else "No recent coverage from the chosen outlets.")


# ---- AI profile (read-only: written by jobs/profiles.py) ------------------------------------------

@dataclass(frozen=True)
class SourceLink:
    label: str
    url: str | None


@dataclass(frozen=True)
class ProfilePoint:
    text: str
    sources: list[SourceLink]


@dataclass(frozen=True)
class Profile:
    sections: list[tuple[str, list[ProfilePoint]]]  # (title, points)
    what_changed: str
    updated: str  # YYYY-MM-DD


PROFILE_TITLES = {"overview": "Overview and sector", "strategy_and_trajectory": "Strategy and trajectory",
                  "bull_case": "Bull case", "bear_case": "Bear case"}


def _source_link(src: dict | None) -> SourceLink | None:
    if src is None:
        return None
    if src["id"].startswith("M"):
        return SourceLink("our figures from SEC filings", None)
    if src["id"].startswith("P"):
        return None  # carried over from our previous profile; its own sources were shown then
    return SourceLink(src.get("outlet") or "source", src.get("url"))


def get_profile(ticker: str) -> Profile | None:
    """The latest validated AI profile, or None. Never generates one (no model calls from the UI)."""
    try:
        with session_scope() as s:
            row = outputs.latest(s, "profile", ticker.upper())
            if row is None:
                return None
            by_id = {src["id"]: src for src in row.sources}
            sections = []
            for key, title in PROFILE_TITLES.items():
                points = []
                for claim in row.content.get(key, []):
                    links = [_source_link(by_id.get(i)) for i in claim["source_ids"]]
                    seen, uniq = set(), []
                    for l in links:
                        if l and (l.label, l.url) not in seen:
                            seen.add((l.label, l.url))
                            uniq.append(l)
                    points.append(ProfilePoint(claim["text"], uniq))
                sections.append((title, points))
            return Profile(sections, row.content.get("what_changed", ""), row.created_at.date().isoformat())
    except OperationalError:
        return None
