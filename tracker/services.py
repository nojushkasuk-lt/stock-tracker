"""The only tracker module app.py imports. Display code asks for data here; it never touches the DB or an API.

Demo mode is read-only (rule 7): everything in this file reads, nothing writes.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from tracker.analysis.metrics import AnnualPoint, Metrics, annual_history, compute_metrics
from tracker.data.charts import get_chart_series
from tracker.db import session_scope
from tracker.models import Fundamental, ListingSeen, Universe
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
