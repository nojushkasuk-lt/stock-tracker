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
from tracker import accounts
from tracker.ai import outputs
from tracker.models import AiOutput, Filing, Fundamental, ListingSeen, Universe
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


def coverage_enabled(email: str | None) -> bool:
    """Live searches only for signed-in users (rule 7: none in demo mode) and only with a Brave key."""
    return bool(email) and bool(config.BRAVE_SEARCH_API_KEY)


@dataclass(frozen=True)
class Coverage:
    links: list[news.NewsLink]
    message: str | None = None  # shown instead of / above the links


def get_coverage(ticker: str, domains: set[str] | None = None, email: str | None = None) -> Coverage:
    """Live, outlet-filtered links for one stock, at most COVERAGE_SEARCHES_PER_USER_PER_DAY per user.
    Results stay in memory; only the search count is stored."""
    if not coverage_enabled(email):
        return Coverage([], "Live coverage search is available to signed-in users.")
    stock = get_stock(ticker)
    if stock is None:
        return Coverage([], "Unknown stock.")
    try:
        with session_scope() as s:
            if not accounts.use_coverage_search(s, email, stock.ticker):
                return Coverage([], f"You've used your {config.COVERAGE_SEARCHES_PER_USER_PER_DAY} coverage searches "
                                    "for today. They reset at midnight UTC.")
            results = news.cached_search(s, news.BraveNews(), news.coverage_query(stock.name, stock.ticker, domains))
    except news.SearchCapReached:
        return Coverage([], "The monthly search limit has been reached. Coverage will be back next month.")
    except Exception:
        return Coverage([], "News search is unavailable right now.")
    links = news.coverage_links(results, news.load_outlets(), domains)
    return Coverage(links, None if links else "No recent coverage from the chosen outlets.")


def coverage_searches_left(email: str) -> int:
    with session_scope() as s:
        return accounts.coverage_searches_left_today(s, email)


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


# ---- signed-in users ------------------------------------------------------------------------------

def sign_in(email: str) -> None:
    with session_scope() as s:
        accounts.ensure_user(s, email)


def get_followable_stocks(email: str | None = None) -> list[Stock]:
    """Stocks a user may pick: the active top 100, plus any soft-removed stock the user already follows."""
    try:
        with session_scope() as s:
            mine = set(accounts.watchlist(s, email)) if email else set()
            rows = s.execute(_query().where(Universe.active | Universe.ticker.in_(mine))
                             .order_by(Universe.market_cap_rank.is_(None), Universe.market_cap_rank, Universe.ticker)).all()
            return [_to_stock(u, ex) for u, ex in rows]
    except OperationalError:
        return []


def get_watchlist(email: str) -> list[Stock]:
    with session_scope() as s:
        tickers = accounts.watchlist(s, email)
        rows = {u.ticker: (u, ex) for u, ex in s.execute(_query().where(Universe.ticker.in_(tickers))).all()}
        return [_to_stock(*rows[t]) for t in tickers if t in rows]


def save_watchlist(email: str, tickers: list[str]) -> str | None:
    """None on success, else a message for the user."""
    try:
        with session_scope() as s:
            accounts.set_watchlist(s, email, tickers)
    except accounts.WatchlistError as e:
        return str(e)
    return None


def get_outlet_choice(email: str) -> set[str]:
    with session_scope() as s:
        return accounts.outlets(s, email)


def save_outlet_choice(email: str, domains: list[str]) -> None:
    with session_scope() as s:
        accounts.set_outlets(s, email, domains)


def refreshes_left(email: str) -> int:
    with session_scope() as s:
        return accounts.refreshes_left_today(s, email)


def request_refresh(email: str, ticker: str) -> str:
    """Rate-limited "Refresh now" (rule 6). Returns a message for the user."""
    from tracker.ai.notes import refresh_stock
    from tracker.data.edgar import EdgarClient
    from tracker.data.filing_text import FilingFetcher

    with session_scope() as s:
        def work() -> bool:
            return refresh_stock(s, ticker, news.BraveNews(), FilingFetcher(EdgarClient())) is not None
        return accounts.request_refresh(s, email, ticker, work).message


# ---- move notes (read-only: written by jobs/daily.py or a refresh) -------------------------------

@dataclass(frozen=True)
class NotePoint:
    text: str
    sources: list[SourceLink]


@dataclass(frozen=True)
class MoveNote:
    date: str
    scope: str                 # stock, industry, market
    scope_label: str
    return_pct: float          # the stock's own move (ours, from the price provider)
    market_return_pct: float | None
    summary: str
    points: list[NotePoint]
    links: list[SourceLink]    # ranked coverage, filtered to the user's outlets when chosen
    confidence: str | None
    headline_based: bool       # no SEC filing behind it: shown with a "based on headlines" label
    written: str               # YYYY-MM-DD HH:MM UTC


SCOPE_LABELS = {"stock": "Company news", "industry": "Moved with its industry", "market": "Moved with the market"}


def _note_view(row: AiOutput, return_pct: float, domains: set[str] | None) -> MoveNote:
    by_id = {src["id"]: src for src in row.sources}
    keep = lambda src: src.get("outlet") == "SEC EDGAR" or not domains or _domain_of(src.get("url")) in domains  # noqa: E731
    points = []
    for c in row.content.get("claims", []):
        links = [SourceLink(by_id[i].get("outlet") or "source", by_id[i].get("url")) for i in c["source_ids"]
                 if i in by_id and keep(by_id[i])]
        points.append(NotePoint(c["text"], links))
    ranked = [SourceLink(by_id[i].get("outlet") or "source", by_id[i].get("url"))
              for i in row.content.get("ranked_source_ids", []) if i in by_id and keep(by_id[i])]
    cited = {i for c in row.content.get("claims", []) for i in c["source_ids"]}
    primary = any(by_id.get(i, {}).get("outlet") == "SEC EDGAR" for i in cited)
    scope = row.kind.removesuffix("_note")
    return MoveNote(row.content.get("date", ""), scope, SCOPE_LABELS.get(scope, scope), return_pct,
                    row.content.get("market_return_pct"), row.content.get("summary", ""), points, ranked,
                    row.confidence, not primary, f"{row.created_at:%Y-%m-%d %H:%M} UTC")


def _domain_of(url: str | None) -> str | None:
    if not url:
        return None
    from tracker.data.news import match_outlet
    o = match_outlet(url, news.load_outlets())
    return o.domain if o else None


def get_move_note(ticker: str, email: str | None = None) -> MoveNote | None:
    """The newest note about the stock: its latest move's note (possibly a shared market or industry note) or
    a newer refresh. None when there is nothing yet. Read-only, also in demo mode."""
    from tracker.models import Move

    try:
        with session_scope() as s:
            ticker = ticker.upper()
            domains = accounts.outlets(s, email) if email else None
            move = s.scalars(select(Move).where(Move.ticker == ticker, Move.note_id.is_not(None))
                             .order_by(Move.date.desc())).first()
            own = outputs.latest(s, "stock_note", ticker)
            row, ret = None, None
            if move is not None:
                row, ret = s.get(AiOutput, move.note_id), float(move.return_pct)
            if own is not None and (row is None or own.created_at > row.created_at):
                row, ret = own, float(own.content.get("return_pct", 0.0))
            return _note_view(row, ret, domains or None) if row is not None else None
    except OperationalError:
        return None


@dataclass(frozen=True)
class MarketStatus:
    date: str
    index_return_pct: float
    level: str                 # none, alert, major
    note: MoveNote | None


def get_market_status(email: str | None = None) -> MarketStatus | None:
    """The latest trading day for the S&P 500 and, on alert days, the shared market note."""
    from tracker.models import MarketDay

    try:
        with session_scope() as s:
            md = s.scalars(select(MarketDay).order_by(MarketDay.date.desc())).first()
            if md is None:
                return None
            note = None
            if md.level != "none":
                row = outputs.latest(s, "market_note", "market")
                if row is not None and row.content.get("date") == md.date.isoformat():
                    domains = accounts.outlets(s, email) if email else None
                    note = _note_view(row, float(md.index_return_pct), domains or None)
            return MarketStatus(md.date.isoformat(), float(md.index_return_pct), md.level, note)
    except OperationalError:
        return None


def dev_sign_in_allowed() -> bool:
    """A plain email box instead of Google, only when running locally (never in prod)."""
    return config.APP_ENV == "local"


def watchlist_max() -> int:
    return config.WATCHLIST_MAX


# ---- performance and risk (from stored daily percent changes; no prices stored) -------------------

@dataclass(frozen=True)
class RangeView:
    label: str          # 1D, 1W, 1M, 6M, 1Y, 5Y
    pct: float
    caption: str        # "Nov 20, last session" / "past year"
    points: str         # SVG polyline points (1000 x 250 box) for the growth line


@dataclass(frozen=True)
class Performance:
    as_of: str
    ranges: list[RangeView]
    risk: "performance.Risk | None"


_RANGE_CAPTIONS = {"1W": "past week", "1M": "past month", "6M": "past 6 months", "1Y": "past year", "5Y": "past 5 years"}


def _returns(s, ticker: str, limit: int = 1300):
    from tracker.models import DailyReturn

    rows = s.execute(select(DailyReturn.date, DailyReturn.return_pct).where(DailyReturn.ticker == ticker)
                     .order_by(DailyReturn.date.desc()).limit(limit)).all()
    return [(d, float(r)) for d, r in reversed(rows)]


def get_performance(ticker: str) -> Performance | None:
    """Range performance (compounded daily changes) and 1-year risk stats vs the S&P 500 (SPY)."""
    from tracker.analysis import performance
    from tracker.data.prices import MARKET_TICKER

    try:
        with session_scope() as s:
            rows = _returns(s, ticker.upper())
            spy = dict(_returns(s, MARKET_TICKER))
    except OperationalError:
        return None
    if not rows:
        return None
    rets = [r for _, r in rows]
    last = rows[-1][0]
    views = []
    for rp in performance.ranges(rets):
        seg = rets[-rp.days:]
        caption = f"{last:%b} {last.day}, last session" if rp.label == "1D" else _RANGE_CAPTIONS[rp.label]
        pts = "0,125 1000,125" if rp.label == "1D" else performance.svg_points(performance.index_line(seg))
        views.append(RangeView(rp.label, rp.pct, caption, pts))
    aligned = [(r, spy[d]) for d, r in rows[-performance.TRADING_DAYS:] if d in spy]
    rk = performance.risk([a for a, _ in aligned], [b for _, b in aligned]) if aligned else None
    return Performance(last.isoformat(), views, rk)


def get_last_moves(tickers: list[str]) -> dict[str, tuple[str, float]]:
    """Latest daily change per ticker: {ticker: (YYYY-MM-DD, pct)}."""
    from sqlalchemy import func

    from tracker.models import DailyReturn

    if not tickers:
        return {}
    try:
        with session_scope() as s:
            latest = (select(DailyReturn.ticker, func.max(DailyReturn.date).label("d"))
                      .where(DailyReturn.ticker.in_([t.upper() for t in tickers])).group_by(DailyReturn.ticker).subquery())
            rows = s.execute(select(DailyReturn.ticker, DailyReturn.date, DailyReturn.return_pct)
                             .join(latest, (DailyReturn.ticker == latest.c.ticker) & (DailyReturn.date == latest.c.d))).all()
            return {t: (d.isoformat(), float(r)) for t, d, r in rows}
    except OperationalError:
        return {}
