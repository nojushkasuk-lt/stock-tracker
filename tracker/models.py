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
    cik: Mapped[str] = mapped_column(Text)  # zero-padded to 10 digits
    name: Mapped[str] = mapped_column(Text)
    industry: Mapped[str] = mapped_column(Text)
    sic_code: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str] = mapped_column(Text, default="US", server_default="US")
    market_cap_rank: Mapped[int | None] = mapped_column(Integer)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    updated_at: Mapped[datetime] = mapped_column(DateTime)


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
    fiscal_period: Mapped[str] = mapped_column(Text, primary_key=True)
    form: Mapped[str] = mapped_column(Text, primary_key=True)
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
