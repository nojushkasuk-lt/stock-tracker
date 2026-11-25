"""The only tracker module app.py imports. Display code asks for data here; it never touches the DB or an API.

Demo mode is read-only (rule 7): everything in this file reads, nothing writes.
"""

from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from tracker.analysis.metrics import AnnualPoint, Metrics, annual_history, compute_metrics
from tracker.data.global_listings import listings, logo_files
from tracker.data.charts import get_chart_series
from tracker.db import session_scope
from tracker import config
from tracker.data import news
from tracker.data.providers import tiingo
from tracker import accounts
from tracker.ai import outputs
from tracker.models import AiOutput, CompanyFacts, Filing, Fundamental, ListingSeen, Universe
from ui.tradingview import tv_symbol


@dataclass(frozen=True)
class Stock:
    ticker: str
    name: str
    industry: str
    rank: int | None
    tv_symbol: str  # e.g. NASDAQ:AAPL
    logo: str | None = None  # small PNG thumbnail URL (Wikimedia Commons), None = show the initial
    country: str = "United States"
    segment: str = "US"
    demo_visible: bool = False
    logo_source: str | None = None

    @property
    def global_listing(self) -> bool:
        return self.ticker in listings()

    @property
    def listing_overview(self) -> str | None:
        row = listings().get(self.ticker)
        return row["about"] if row else None

    @property
    def quote_embeddable(self) -> bool:
        row = listings().get(self.ticker)
        return row is None or row["embed"] == "1"

    @property
    def chart_symbol(self) -> str | None:
        if self.quote_embeddable:
            return self.tv_symbol
        return listings()[self.ticker]["alternate_symbol"] or None

    @property
    def alternate_chart_label(self) -> str | None:
        row = listings().get(self.ticker)
        return (row["alternate_label"] or None) if row else None

    @property
    def region(self) -> str:
        return region_of(self.country)

    @property
    def foreign_filer(self) -> bool:
        return self.segment != "US" and not self.global_listing


REGIONS = {"United States": "North America", "Canada": "North America", "Mexico": "North America",
           "Japan": "Asia", "South Korea": "Asia", "Taiwan": "Asia", "China": "Asia", "India": "Asia", "Hong Kong": "Asia",
           "Singapore": "Asia", "Australia": "Asia-Pacific"}


# ---- who may see price-provider figures (rule 13) ----------------------------------------------------------

_viewer_email: ContextVar[str | None] = ContextVar("viewer_email", default=None)


def set_viewer(email: str | None) -> None:
    """The web layer names the signed-in viewer once per request (each request has its own context)."""
    _viewer_email.set(email)


def price_data_visible(email: str | None = None) -> bool:
    """Daily % changes and everything made from them are provider data. Until a provider allows showing them to
    others (config.PRICE_DATA_DISPLAY = "all"), only the owner sees them: that is personal use."""
    if config.PRICE_DATA_DISPLAY == "all":
        return True
    e = (email if email is not None else _viewer_email.get()) or ""
    return bool(config.OWNER_EMAIL) and e.strip().lower() == config.OWNER_EMAIL.strip().lower()


def region_of(country: str | None) -> str:
    if not country:
        return "North America"
    return REGIONS.get(country, "Europe" if country in EUROPE else "Other")


EUROPE = {"United Kingdom", "Ireland", "Netherlands", "Germany", "France", "Switzerland", "Denmark", "Sweden", "Norway",
          "Finland", "Spain", "Italy", "Belgium", "Luxembourg", "Austria", "Portugal"}


def _query():
    return (select(Universe, ListingSeen.exchange, CompanyFacts.logo_url, CompanyFacts.country)
            .join(ListingSeen, ListingSeen.ticker == Universe.ticker, isouter=True)
            .join(CompanyFacts, CompanyFacts.ticker == Universe.ticker, isouter=True))


def _to_stock(u: Universe, exchange: str | None, logo_url: str | None = None, country: str | None = None) -> Stock:
    from tracker.data.wikidata import commons_logo, logo_thumb

    segment = u.region or "US"
    logo_file = logo_files().get(u.ticker) if not logo_url else None
    curated_logo, logo_source = commons_logo(logo_file) if logo_file else (None, None)
    return Stock(
        u.ticker, u.name, u.industry, u.market_cap_rank,
        u.ticker if u.ticker in listings() else tv_symbol(u.ticker, exchange),
        logo_thumb(logo_url, 128) if logo_url else curated_logo,
        u.country or country or "United States", segment,
        demo_visible=u.active and (u.is_demo or segment in config.INTL_REGIONS),
        logo_source=logo_source,
    )


def register_global_stocks() -> None:
    from tracker.db import create_tables
    from tracker.data.global_listings import seed_global_listings

    # Production already has its schema. A fresh local install needs the universe table.
    if config.APP_ENV != "prod":
        create_tables()
    with session_scope() as session:
        seed_global_listings(session)


def get_international_stocks() -> list[Stock]:
    """All active European and Asian stocks, including US-listed shares and home-market listings."""
    with session_scope() as s:
        rows = s.execute(
            _query().where(Universe.active, Universe.region.in_(config.INTL_REGIONS))
            .order_by(Universe.market_cap_rank.is_(None), Universe.market_cap_rank, Universe.name)
        ).all()
        return [_to_stock(*row) for row in rows]


def get_demo_stocks() -> list[Stock]:
    """The demo stocks (current top 20), largest first. Empty if the database is not set up yet."""
    try:
        with session_scope() as s:
            rows = s.execute(
                _query().where(Universe.is_demo, Universe.active).order_by(Universe.market_cap_rank)
            ).all()
            return [_to_stock(*r) for r in rows]
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


_FORM_LABEL = {"10-K": "Annual report", "10-Q": "Quarterly report", "8-K": "Current report",
               "20-F": "Annual report", "6-K": "Interim report"}


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


def get_notable_move(stock: Stock) -> tiingo.NotableMove | None:
    return None if stock.global_listing else tiingo.notable_move(stock.ticker)


def get_coverage(ticker: str, domains: set[str] | None = None, email: str | None = None,
                 move: tiingo.NotableMove | None = None) -> Coverage:
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
            query = news.coverage_query(stock.name, stock.ticker, domains, direction=move.direction if move else None)
            freshness = f"{move.previous_session}to{move.session}" if move else "pw"
            results = news.cached_search(s, news.BraveNews(), query, freshness=freshness)
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
    title: str = ""


@dataclass(frozen=True)
class Profile:
    about: list[ProfilePoint]                          # sentences of the About paragraph
    sections: list[tuple[str, list[ProfilePoint]]]     # (title, points), in page order
    what_changed: str
    updated: str  # YYYY-MM-DD
    filing: str = ""                                   # e.g. "10-K filed 2026-10-31"


PROFILE_TITLES = {"business": "Products & revenue", "strategy_and_trajectory": "Strategy & outlook",
                  "latest_report": "Latest report", "bull_case": "Bull case", "bear_case": "Bear case",
                  "what_to_watch": "What to watch"}
_V1_TITLES = {"strategy_and_trajectory": "Strategy & outlook", "bull_case": "Bull case", "bear_case": "Bear case"}


def _source_link(src: dict | None) -> SourceLink | None:
    if src is None:
        return None
    if src["id"].startswith("M"):
        return SourceLink("our figures from SEC filings", None)
    if src["id"].startswith("P"):
        return None  # carried over from our previous profile; its own sources were shown then
    return SourceLink(src.get("outlet") or "source", src.get("url"))


def get_profile(ticker: str) -> Profile | None:
    """The latest validated AI profile, or None. Never generates one (no model calls from the UI).
    Reads both the current format (about + titled points) and version 1 (overview + plain claims)."""
    try:
        with session_scope() as s:
            row = outputs.latest(s, "profile", ticker.upper())
            if row is None:
                return None
            by_id = {src["id"]: src for src in row.sources}

            def point(item: dict) -> ProfilePoint:
                seen, uniq = set(), []
                for l in (_source_link(by_id.get(i)) for i in item.get("source_ids", [])):
                    if l and (l.label, l.url) not in seen:
                        seen.add((l.label, l.url))
                        uniq.append(l)
                return ProfilePoint(item["text"], uniq, item.get("title", ""))

            c = row.content
            v2 = "about" in c or "business" in c
            about = [point(x) for x in c.get("about" if v2 else "overview", [])]
            titles = PROFILE_TITLES if v2 else _V1_TITLES
            sections = [(title, [point(x) for x in c.get(key, [])]) for key, title in titles.items() if c.get(key)]
            return Profile(about, sections, c.get("what_changed", ""), row.created_at.date().isoformat(), c.get("filing", ""))
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
            return [_to_stock(*r) for r in rows]
    except OperationalError:
        return []


def get_watchlist(email: str) -> list[Stock]:
    with session_scope() as s:
        tickers = accounts.watchlist(s, email)
        rows = {r[0].ticker: r for r in s.execute(_query().where(Universe.ticker.in_(tickers))).all()}
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
    if ticker.upper() in listings() or not price_data_visible(email):
        return "Move notes are unavailable for this listing or account."

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


@dataclass(frozen=True)
class ClosingNews:
    date: str
    points: list[NotePoint]
    links: list[SourceLink]


def _closing_news_for(tickers: list[str]) -> dict[str, ClosingNews]:
    try:
        with session_scope() as session:
            rows = session.scalars(select(AiOutput).where(
                AiOutput.kind == "closing_news", AiOutput.scope_key.in_(tickers),
            ).order_by(AiOutput.content["date"].as_string().desc(), AiOutput.id.desc()))
            result: dict[str, ClosingNews] = {}
            for row in rows:
                if row.scope_key in result:
                    continue
                by_id = {src["id"]: SourceLink(src["outlet"] or "Source", src["url"])
                         for src in row.sources if src["url"]}
                points = [NotePoint(claim["text"], [by_id[i] for i in claim["source_ids"] if i in by_id])
                          for claim in row.content["claims"]]
                result[row.scope_key] = ClosingNews(row.content["date"], points, list(by_id.values()))
                if len(result) == len(tickers):
                    break
            return result
    except OperationalError:
        return {}


def get_closing_news(ticker: str = "market") -> ClosingNews | None:
    return _closing_news_for([ticker]).get(ticker)


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

    if not price_data_visible(email):
        return None  # notes explain provider move sizes

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

    if not price_data_visible(email):
        return None

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

    if not price_data_visible():
        return []

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


def get_watchlist_change(stocks: list[Stock]) -> tiingo.WatchlistChange | None:
    return tiingo.watchlist_change([stock.ticker for stock in stocks if not stock.global_listing])


def get_last_moves(tickers: list[str]) -> dict[str, tuple[str, float]]:
    """Latest daily change per ticker: {ticker: (YYYY-MM-DD, pct)}."""
    from sqlalchemy import func

    from tracker.models import DailyReturn

    if not tickers or not price_data_visible():
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


# ---- key facts (Wikidata) -------------------------------------------------------------------------

@dataclass(frozen=True)
class KeyFacts:
    ceo: str | None
    ceo_since: str | None      # YYYY-MM-DD
    headquarters: str | None
    country: str | None
    founded: int | None
    employees: int | None
    website: str | None
    wikipedia_url: str | None
    wikidata_url: str
    fetched: str               # YYYY-MM-DD


def get_key_facts(ticker: str) -> KeyFacts | None:
    try:
        with session_scope() as s:
            f = s.get(CompanyFacts, ticker.upper())
            if f is None:
                return None
            return KeyFacts(f.ceo, f.ceo_since.isoformat() if f.ceo_since else None, f.headquarters, f.country,
                            f.founded, f.employees, f.website, f.wikipedia_url,
                            f"https://www.wikidata.org/wiki/{f.qid}", f.fetched_at.date().isoformat())
    except OperationalError:
        return None


# ---- price chart (local development only; rule 13: in prod the TradingView chart is shown instead) ---

@dataclass(frozen=True)
class ChartRange:
    label: str            # 1D, 1W, 1M, 6M, 1Y, 5Y, MAX
    pct: float            # change over the range
    caption: str          # "Nov 20" / "past month" / "since Dec 1980"
    points: str           # SVG polyline points in a 1000 x 250 box
    series: list          # [[label, value], ...] matching the points, for the hover readout
    low: float
    high: float


@dataclass(frozen=True)
class PriceChart:
    last_close: float
    ranges: list[ChartRange]
    session: str | None = None  # YYYY-MM-DD of the 1D range's session


_CHART_RANGES = [("1M", 21, "past month"), ("6M", 126, "past 6 months"), ("1Y", 252, "past year"), ("5Y", 1260, "past 5 years")]


def _chart_range(label, caption, pts, fmt, pct=None) -> ChartRange:
    from tracker.analysis.performance import svg_points

    values = [v for _, v in pts]
    step = max(1, -(-len(pts) // 160))
    sampled = pts[::step] + ([pts[-1]] if (len(pts) - 1) % step else [])
    return ChartRange(label, pct if pct is not None else (values[-1] / values[0] - 1) * 100, caption,
                      svg_points([v for _, v in sampled], max_points=len(sampled)),
                      [[fmt(t), round(v, 2)] for t, v in sampled], min(values), max(values))


def get_price_chart(ticker: str) -> PriceChart | None:
    """One chart with 1D to MAX, from the dev chart provider (in-memory only). None in prod."""
    from datetime import UTC, datetime

    series = get_chart_series(ticker.upper())
    if series is None or len(series.points) < 2:
        return None
    closes = series.points
    day = lambda d: f"{d:%b} {d.day}, {d.year}"  # noqa: E731
    clock = lambda t: datetime.fromtimestamp(t, UTC).strftime("%b %d %H:%M UTC")  # noqa: E731
    out = []
    intra = series.intraday
    if len(intra.get("1D", [])) >= 2:
        # 1D: today's line, change against the previous close.
        d = intra["1D"]
        prev = closes[-2][1] if len(closes) >= 2 else d[0][1]
        last_day = datetime.fromtimestamp(d[-1][0], UTC).date()
        caption = f"{last_day:%b} {last_day.day}"
        out.append(_chart_range("1D", caption, d, clock, (d[-1][1] / prev - 1) * 100))
        session = last_day
    else:
        out.append(_chart_range("1D", f"{closes[-1][0]:%b} {closes[-1][0].day}", closes[-2:], day))
        session = closes[-1][0]
    if len(intra.get("1W", [])) >= 2:
        out.append(_chart_range("1W", "past week", intra["1W"], clock))
    else:
        out.append(_chart_range("1W", "past week", closes[-6:], day))
    for label, n, caption in _CHART_RANGES:
        if len(closes) > n * 0.9:
            out.append(_chart_range(label, caption, closes[-(n + 1):], day))
    first = closes[0][0]
    out.append(_chart_range("MAX", f"since {first:%b} {first.year}", closes, day))
    return PriceChart(closes[-1][1], out, session.isoformat())


# ---- markets: index funds and ETFs -----------------------------------------------------------------

@dataclass(frozen=True)
class MarketTile:
    ticker: str
    name: str
    group: str
    tracks: str
    issuer: str
    day: float | None
    month: float | None
    year: float | None
    spark: str | None       # SVG points for a 1-year growth line (local development only)
    followed: bool


def _tile(fund, rets: list[float], followed: bool, spark: bool) -> MarketTile:
    from tracker.analysis import performance as pf

    def last(n):
        return pf.compound(rets[-n:]) if len(rets) >= n * 0.9 else None
    line = pf.svg_points(pf.index_line(rets[-252:]), width=120, height=36, pad=3, max_points=60) if spark and len(rets) > 40 else None
    return MarketTile(fund.ticker, fund.name, fund.group, fund.tracks, fund.issuer,
                      rets[-1] if rets else None, last(21), last(252), line, followed)


def _sparklines_allowed() -> bool:
    return config.CHART_PROVIDER != "none"  # same gate as the custom chart (rule 13)


def get_markets(email: str | None = None) -> list[tuple[str, list[MarketTile]]]:
    """All funds by group, with day / 1-month / 1-year change from stored daily changes."""
    from tracker.data import markets

    try:
        with session_scope() as s:
            mine = set(accounts.followed_markets(s, email)) if email else set()
            data = {f.ticker: [r for _, r in _returns(s, f.ticker, 260)] for f in markets.load()}
    except OperationalError:
        return []
    spark = _sparklines_allowed()
    return [(g, [_tile(f, data[f.ticker], f.ticker in mine, spark) for f in markets.load() if f.group == g]) for g in markets.GROUPS]


def get_followed_markets(email: str | None) -> list[MarketTile]:
    from tracker.data import markets

    by = markets.by_ticker()
    try:
        with session_scope() as s:
            mine = (accounts.followed_markets(s, email) if email else []) or list(markets.DEFAULT_FOLLOWED)
            data = {t: [r for _, r in _returns(s, t, 260)] for t in mine if t in by}
    except OperationalError:
        return []
    spark = _sparklines_allowed()
    return [_tile(by[t], data[t], True, spark) for t in mine if t in by]


def save_markets(email: str, tickers: list[str]) -> str | None:
    try:
        with session_scope() as s:
            accounts.set_markets(s, email, tickers)
    except accounts.WatchlistError as e:
        return str(e)
    return None


@dataclass(frozen=True)
class FundPage:
    ticker: str
    name: str
    group: str
    tracks: str
    issuer: str
    tv_symbol: str
    perf: Performance | None
    chart: PriceChart | None
    followed: bool


def get_fund(ticker: str, email: str | None = None) -> FundPage | None:
    from tracker.data import markets

    f = markets.by_ticker().get(ticker.upper())
    if f is None:
        return None
    try:
        with session_scope() as s:
            followed = bool(email) and f.ticker in accounts.followed_markets(s, email)
    except OperationalError:
        followed = False
    return FundPage(f.ticker, f.name, f.group, f.tracks, f.issuer, f.tv_symbol, get_performance(f.ticker),
                    get_price_chart(f.ticker), followed)


# ---- portfolio: performance since each stock's start date ------------------------------------------------

@dataclass(frozen=True)
class Holding:
    stock: Stock
    start: str | None          # YYYY-MM-DD performance is measured from
    since_start: float | None  # compounded daily changes after the start date
    day: float | None
    day_date: str | None
    spark: str | None          # since-start growth line (local development only)


def get_portfolio(email: str) -> tuple[list[Holding], float | None, float | None]:
    """(holdings, equal-weight average since start, S&P 500 (SPY) over the same windows, averaged)."""
    from tracker.analysis import performance as pf
    from tracker.data.prices import MARKET_TICKER

    stocks = get_watchlist(email)
    out, mine, bench = [], [], []
    spark = _sparklines_allowed()
    with session_scope() as s:
        starts = accounts.start_dates(s, email)
        spy = _returns(s, MARKET_TICKER)
        for st in stocks:
            rows = _returns(s, st.ticker)
            start = starts.get(st.ticker)
            after = [r for d, r in rows if start and d > start]
            since = pf.compound(after) if after else (0.0 if start else None)
            if since is not None:
                mine.append(since)
                bench.append(pf.compound([r for d, r in spy if d > start]))
            line = pf.svg_points(pf.index_line(after), width=120, height=36, pad=3, max_points=60) if spark and len(after) > 2 else None
            out.append(Holding(st, start.isoformat() if start else None, since,
                               rows[-1][1] if rows else None, rows[-1][0].isoformat() if rows else None, line))
    avg = sum(mine) / len(mine) if mine else None
    bavg = sum(bench) / len(bench) if bench else None
    return out, avg, bavg


def set_start_date(email: str, ticker: str, start) -> str | None:
    try:
        with session_scope() as s:
            accounts.set_start_date(s, email, ticker, start)
    except accounts.WatchlistError as e:
        return str(e)
    return None


# ---- preferences, onboarding, notifications, share links -------------------------------------------------

@dataclass(frozen=True)
class Prefs:
    stock_alerts: bool
    market_alerts: bool
    alert_threshold_pct: float
    email_alerts: bool
    digest: str
    home: str
    perf_basis: str
    onboarded: bool


def get_prefs(email: str) -> Prefs:
    with session_scope() as s:
        p = accounts.prefs(s, email)
        return Prefs(p.stock_alerts, p.market_alerts, float(p.alert_threshold_pct), p.email_alerts, p.digest, p.home,
                     p.perf_basis, p.onboarded_at is not None)


def save_prefs(email: str, **values) -> str | None:
    try:
        with session_scope() as s:
            accounts.set_prefs(s, email, **values)
    except ValueError as e:
        return str(e)
    return None


def needs_onboarding(email: str) -> bool:
    with session_scope() as s:
        return accounts.needs_onboarding(s, email)


def finish_onboarding(email: str) -> None:
    from datetime import UTC, datetime

    with session_scope() as s:
        accounts.set_prefs(s, email, onboarded_at=datetime.now(UTC).replace(tzinfo=None))


@dataclass(frozen=True)
class Alert:
    kind: str
    title: str
    body: str
    url: str
    created: str      # YYYY-MM-DD HH:MM
    unread: bool


def get_alerts(email: str, limit: int = 30) -> list[Alert]:
    if not price_data_visible(email):
        return []  # every alert is a provider move
    with session_scope() as s:
        return [Alert(n.kind, n.title, n.body, n.url, f"{n.created_at:%Y-%m-%d %H:%M}", n.read_at is None)
                for n in accounts.notifications(s, email, limit)]


def unread_alerts(email: str) -> int:
    if not price_data_visible(email):
        return 0
    try:
        with session_scope() as s:
            return accounts.unread_count(s, email)
    except OperationalError:
        return 0


def mark_alerts_read(email: str) -> None:
    with session_scope() as s:
        accounts.mark_read(s, email)


def share_link_valid(token: str | None) -> bool:
    try:
        with session_scope() as s:
            return accounts.share_link_valid(s, token)
    except OperationalError:
        return False


def use_share_link(token: str) -> bool:
    with session_scope() as s:
        return accounts.use_share_link(s, token)


def get_start_dates(email: str) -> dict[str, str]:
    with session_scope() as s:
        return {t: d.isoformat() for t, d in accounts.start_dates(s, email).items()}


def get_followed_market_tickers(email: str) -> list[str]:
    with session_scope() as s:
        return accounts.followed_markets(s, email)


def get_market_list():
    from tracker.data import markets

    return markets.load()


@dataclass(frozen=True)
class EarningsEntry:
    stock: Stock
    upcoming_date: date | None
    announcement: str | None
    latest: FilingLink | None


def get_earnings_calendar(stocks: list[Stock]) -> list[EarningsEntry]:
    from tracker.data import earnings

    if not stocks:
        return []
    dates = earnings.announced_dates(datetime.now(UTC).date())
    with session_scope() as session:
        reports = earnings.latest_reports(session, [stock.ticker for stock in stocks])
        entries = []
        for stock in stocks:
            day, announcement = dates.get(stock.ticker, (None, None))
            report = reports.get(stock.ticker)
            latest = FilingLink(report.form, report.filed_at.date().isoformat(), report.url,
                                "Earnings release filing" if report.form == "8-K" else _FORM_LABEL[report.form]) if report else None
            entries.append(EarningsEntry(stock, day, announcement, latest))
    return sorted(entries, key=lambda entry: (entry.upcoming_date or date.max, entry.stock.name.casefold()))


@dataclass(frozen=True)
class WeeklyBrief:
    start: str
    end: str
    sections: list[tuple[str, list[NotePoint]]]


def get_weekly_brief() -> WeeklyBrief | None:
    from tracker.ai.weekly_brief import KIND, TOPICS

    with session_scope() as session:
        row = session.scalars(select(AiOutput).where(AiOutput.kind == KIND)
                              .order_by(AiOutput.scope_key.desc(), AiOutput.id.desc()).limit(1)).first()
        if row is None:
            return None
        sources = {source["id"]: SourceLink(source["outlet"], source["url"]) for source in row.sources}
        sections = [
            (topic, [NotePoint(claim["text"], [sources[i] for i in dict.fromkeys(claim["source_ids"])])
                     for claim in row.content[topic.lower()]])
            for topic in TOPICS if row.content.get(topic.lower())
        ]
        return WeeklyBrief(row.content["start"], row.content["end"], sections)


# ---- news page ------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class NewsPage:
    market: MarketStatus | None
    moves: list[tuple[Stock, MoveNote]]   # notes on recent big moves in the viewer's stocks, newest first
    live: Coverage | None                 # market headlines from a live search (signed in, on request)
    searches_left: int
    outlets: str
    weekly_brief: WeeklyBrief | None = None
    closing_news: ClosingNews | None = None
    stock_closing_news: list[tuple[Stock, ClosingNews]] = field(default_factory=list)


class _Hidden(Exception):
    pass


def get_news_page(email: str | None, live: bool = False, days: int = 30) -> NewsPage:
    """Stored notes (ours) for the market and the viewer's stocks; live headlines only when asked for, within
    the user's daily coverage cap (results are kept in memory only, rule 13)."""
    from datetime import date as _date, timedelta

    from tracker.models import Move

    stocks = get_watchlist(email) if email else get_demo_stocks()
    by = {s.ticker: s for s in stocks}
    moves: list[tuple[Stock, MoveNote]] = []
    domains: set[str] = set()
    try:
        with session_scope() as s:
            domains = accounts.outlets(s, email) if email else set()
            if not price_data_visible(email):
                raise _Hidden
            since = _date.today() - timedelta(days=days)
            rows = s.scalars(select(Move).where(Move.ticker.in_(list(by)), Move.note_id.is_not(None), Move.date >= since)
                             .order_by(Move.date.desc(), Move.ticker)).all()
            for m in rows:
                note = s.get(AiOutput, m.note_id)
                if note is not None:
                    moves.append((by[m.ticker], _note_view(note, float(m.return_pct), domains or None)))
    except (OperationalError, _Hidden):
        pass
    coverage = None
    if live:
        coverage = _market_coverage(email, domains or None)
    names = [o.name for o in news.load_outlets() if o.domain in domains]
    closing_by_ticker = _closing_news_for(["market", *by])
    closing = closing_by_ticker.get("market")
    stock_closing = [(stock, note) for stock in stocks if (note := closing_by_ticker.get(stock.ticker))
                     and (closing is None or note.date >= closing.date)]
    return NewsPage(get_market_status(email), moves, coverage,
                    coverage_searches_left(email) if email else 0, ", ".join(names) if names else "all outlets",
                    get_weekly_brief(), closing, stock_closing)


def _market_coverage(email: str | None, domains: set[str] | None) -> Coverage:
    if not coverage_enabled(email):
        return Coverage([], "Live coverage search is available to signed-in users.")
    try:
        with session_scope() as s:
            if not accounts.use_coverage_search(s, email, "MARKET"):
                return Coverage([], f"You've used your {config.COVERAGE_SEARCHES_PER_USER_PER_DAY} coverage searches "
                                    "for today. They reset at midnight UTC.")
            results = news.cached_search(s, news.BraveNews(), news.market_query(domains), freshness="pd")
    except news.SearchCapReached:
        return Coverage([], "The monthly search limit has been reached. Coverage will be back next month.")
    except Exception:
        return Coverage([], "News search is unavailable right now.")
    links = news.coverage_links(results, news.load_outlets(), domains)
    return Coverage(links, None if links else "No market coverage from the chosen outlets in the past day.")


# ---- shared links (owner) -----------------------------------------------------------------------------------

@dataclass(frozen=True)
class SharedLink:
    token: str
    label: str
    created: str
    last_used: str | None
    uses: int
    revoked: bool


def get_share_links() -> list[SharedLink]:
    with session_scope() as s:
        return [SharedLink(l.token, l.label, f"{l.created_at:%Y-%m-%d}", f"{l.last_used_at:%Y-%m-%d %H:%M}" if l.last_used_at else None,
                           l.uses or 0, l.revoked_at is not None) for l in accounts.share_links(s)]


def create_share_link(label: str) -> str:
    with session_scope() as s:
        return accounts.create_share_link(s, label).token


def revoke_share_link(token: str) -> None:
    with session_scope() as s:
        accounts.revoke_share_link(s, token)


def known_user(email: str) -> bool:
    from tracker.models import User

    try:
        with session_scope() as s:
            return s.get(User, accounts.normalize_email(email)) is not None
    except OperationalError:
        return False


def home_path(email: str) -> str:
    """Where a signed-in user lands: the setup steps the first time, then their chosen start page."""
    try:
        if needs_onboarding(email):
            return "/welcome"
        return {"market": "/market", "news": "/news"}.get(get_prefs(email).home, "/portfolio")
    except OperationalError:
        return "/portfolio"
