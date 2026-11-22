"""The only tracker module app.py imports. Display code asks for data here; it never touches the DB or an API.

Demo mode is read-only (rule 7): everything in this file reads, nothing writes.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from tracker.data.charts import get_chart_series
from tracker.db import session_scope
from tracker.models import ListingSeen, Universe
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


def get_chart_points(ticker: str) -> list[tuple[str, float]] | None:
    """[(YYYY-MM-DD, close)] for the custom chart, or None when it is switched off (use the TradingView widgets)."""
    series = get_chart_series(ticker.upper())
    return None if series is None else [(d.isoformat(), v) for d, v in series.points]
