"""SQLAlchemy models. Mirror schema.sql (this file is the source of truth)."""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# BIGSERIAL on Postgres; plain INTEGER primary key on SQLite so it autoincrements.
BigId = BigInteger().with_variant(Integer, "sqlite")
# JSONB on Postgres, JSON on SQLite.
Json = JSON().with_variant(JSONB, "postgresql")
# Floats are fine for percentages and USD figures here; avoids SQLite Decimal warnings.
Num = Numeric(asdecimal=False)


class Base(DeclarativeBase):
    pass


class Universe(Base):
    __tablename__ = "universe"
    __table_args__ = (Index("idx_universe_industry", "industry"),)

    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    cik: Mapped[str] = mapped_column(Text)  # zero-padded to 10 digits, empty for market-data-only listings
    name: Mapped[str] = mapped_column(Text)
    industry: Mapped[str] = mapped_column(Text)
    sic_code: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str] = mapped_column(Text, default="US", server_default="US")  # US, Europe, Asia
    country: Mapped[str | None] = mapped_column(Text)  # set for non-US listings (config/international.csv)
    market_cap_rank: Mapped[int | None] = mapped_column(Integer)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class CompanyFacts(Base):
    """Key facts and logo from Wikidata (CC0), refreshed weekly by jobs/facts.py. Shown with their source."""

    __tablename__ = "company_facts"

    ticker: Mapped[str] = mapped_column(ForeignKey("universe.ticker"), primary_key=True)
    qid: Mapped[str] = mapped_column(Text)
    logo_url: Mapped[str | None] = mapped_column(Text)        # Wikimedia Commons file
    ceo: Mapped[str | None] = mapped_column(Text)
    ceo_since: Mapped[date | None] = mapped_column(Date)
    headquarters: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    founded: Mapped[int | None] = mapped_column(Integer)
    employees: Mapped[int | None] = mapped_column(Integer)
    website: Mapped[str | None] = mapped_column(Text)
    wikipedia_url: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime)


class ListingSeen(Base):
    __tablename__ = "listings_seen"

    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    cik: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    exchange: Mapped[str | None] = mapped_column(Text)
    sic_code: Mapped[str | None] = mapped_column(Text)
    is_candidate: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    first_seen: Mapped[datetime] = mapped_column(DateTime)


class User(Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(Text, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    last_login: Mapped[datetime | None] = mapped_column(DateTime)


class UserWatchlist(Base):
    __tablename__ = "user_watchlist"

    email: Mapped[str] = mapped_column(ForeignKey("users.email", ondelete="CASCADE"), primary_key=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("universe.ticker"), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime)
    start_date: Mapped[date | None] = mapped_column(Date)  # performance is measured from here (default: added_at)


class UserMarket(Base):
    """Index funds / ETFs a user follows (config/markets.csv tickers)."""

    __tablename__ = "user_markets"

    email: Mapped[str] = mapped_column(ForeignKey("users.email", ondelete="CASCADE"), primary_key=True)
    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime)


class UserPrefs(Base):
    __tablename__ = "user_prefs"

    email: Mapped[str] = mapped_column(ForeignKey("users.email", ondelete="CASCADE"), primary_key=True)
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime)
    stock_alerts: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    market_alerts: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    alert_threshold_pct: Mapped[float] = mapped_column(Num, default=5.0, server_default="5.0")
    email_alerts: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    digest: Mapped[str] = mapped_column(Text, default="weekly", server_default="weekly")    # off, daily, weekly
    home: Mapped[str] = mapped_column(Text, default="portfolio", server_default="portfolio")  # portfolio, market, news
    perf_basis: Mapped[str] = mapped_column(Text, default="start", server_default="start")    # start, 1D, 1M, 1Y


class Notification(Base):
    """In-site alerts (and the record of what was emailed). Text is our own note summary, never article text."""

    __tablename__ = "notifications"
    __table_args__ = (Index("idx_notifications_user", "email", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(ForeignKey("users.email", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)            # stock_move, market_move, digest
    ticker: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)             # path on our site
    dedupe_key: Mapped[str] = mapped_column(Text)      # one alert per user per move
    created_at: Mapped[datetime] = mapped_column(DateTime)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime)


class ShareLink(Base):
    """Private-access links the owner hands out (e.g. to an employer). The site is closed without one."""

    __tablename__ = "share_links"

    token: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    uses: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class UserOutlet(Base):
    __tablename__ = "user_outlets"

    email: Mapped[str] = mapped_column(ForeignKey("users.email", ondelete="CASCADE"), primary_key=True)
    domain: Mapped[str] = mapped_column(Text, primary_key=True)


class DailyReturn(Base):
    """Daily percent change per stock and for 'SPY'. The only price-derived data we keep."""

    __tablename__ = "daily_returns"
    __table_args__ = (Index("idx_returns_date", "date"),)

    ticker: Mapped[str] = mapped_column(Text, primary_key=True)  # no FK: includes SPY
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    return_pct: Mapped[float] = mapped_column(Num)


class MarketDay(Base):
    __tablename__ = "market_days"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    index_return_pct: Mapped[float] = mapped_column(Num)
    level: Mapped[str] = mapped_column(Text)  # none, alert, major


class Fundamental(Base):
    __tablename__ = "fundamentals"

    ticker: Mapped[str] = mapped_column(ForeignKey("universe.ticker"), primary_key=True)
    metric: Mapped[str] = mapped_column(Text, primary_key=True)
    period_end: Mapped[date] = mapped_column(Date, primary_key=True)
    duration_days: Mapped[int] = mapped_column(Integer, primary_key=True)  # 0 = point in time
    fiscal_period: Mapped[str] = mapped_column(Text)
    form: Mapped[str] = mapped_column(Text)
    value: Mapped[float] = mapped_column(Num)
    unit: Mapped[str] = mapped_column(Text)
    accession: Mapped[str] = mapped_column(Text)
    filed_at: Mapped[date] = mapped_column(Date)


class Filing(Base):
    __tablename__ = "filings"
    __table_args__ = (
        Index(
            "idx_filings_unprocessed",
            "processed_at",
            postgresql_where=text("processed_at IS NULL"),
            sqlite_where=text("processed_at IS NULL"),
        ),
    )

    accession: Mapped[str] = mapped_column(Text, primary_key=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("universe.ticker"))
    form: Mapped[str] = mapped_column(Text)
    items: Mapped[str | None] = mapped_column(Text)
    filed_at: Mapped[datetime] = mapped_column(DateTime)
    period_end: Mapped[date | None] = mapped_column(Date)
    url: Mapped[str] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)


class AiOutput(Base):
    __tablename__ = "ai_outputs"
    __table_args__ = (
        UniqueConstraint("kind", "scope_key", "input_hash"),
        Index("idx_ai_outputs_lookup", "kind", "scope_key", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(Text)  # profile, stock_note, industry_note, market_note, summary
    scope_key: Mapped[str] = mapped_column(Text)  # ticker, 'industry:<name>', or 'market'
    model: Mapped[str] = mapped_column(Text)
    input_hash: Mapped[str] = mapped_column(Text)
    content: Mapped[dict] = mapped_column(Json)
    sources: Mapped[list] = mapped_column(Json)  # [{id, url, outlet}]
    confidence: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime)


class Move(Base):
    __tablename__ = "moves"
    __table_args__ = (
        UniqueConstraint("ticker", "date"),
        Index("idx_moves_date", "date"),
    )

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("universe.ticker"))
    date: Mapped[date] = mapped_column(Date)
    return_pct: Mapped[float] = mapped_column(Num)
    scope: Mapped[str] = mapped_column(Text)  # market, industry, stock
    market_return_pct: Mapped[float | None] = mapped_column(Num)
    industry_return_pct: Mapped[float | None] = mapped_column(Num)
    note_id: Mapped[int | None] = mapped_column(ForeignKey("ai_outputs.id", name="fk_moves_note"))
    status: Mapped[str] = mapped_column(Text)  # pending, explained, no_catalyst, recheck
    recheck_after: Mapped[datetime | None] = mapped_column(DateTime)


class RefreshRequest(Base):
    __tablename__ = "refresh_requests"
    __table_args__ = (Index("idx_refresh_user_day", "email", "requested_at"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(ForeignKey("users.email", ondelete="CASCADE"))
    ticker: Mapped[str] = mapped_column(ForeignKey("universe.ticker"))
    kind: Mapped[str] = mapped_column(Text)  # refresh, coverage_search
    requested_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(Text)  # served_from_cache, done, refused_cap, failed


class UsageLog(Base):
    __tablename__ = "usage_log"
    __table_args__ = (Index("idx_usage_month", "created_at"),)

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    job: Mapped[str] = mapped_column(Text)  # daily, summary, profiles, refresh, coverage
    model: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    search_calls: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 4, asdecimal=False))


class AiBatch(Base):
    """A Message Batch waiting for results. items holds what is needed to validate and save each result
    (custom_id -> scope, model, prompt hash, sources). Deleted contents after collection keep the table small."""
    __tablename__ = "ai_batches"

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # msgbatch_...
    job: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)                  # ai_outputs.kind the results become
    created_at: Mapped[datetime] = mapped_column(DateTime)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime)
    items: Mapped[dict] = mapped_column(Json)
