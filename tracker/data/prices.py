"""Price provider interface. Rule 13: providers return daily percent changes only, never prices.

Only the percent changes are stored (daily_returns). Charts and quotes come from TradingView widgets.
"""

from datetime import date
from typing import Protocol

from sqlalchemy import insert
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from tracker import config
from tracker.models import DailyReturn

# ticker -> [(date, percent change vs the previous trading day)]
Returns = dict[str, list[tuple[date, float]]]

MARKET_TICKER = "SPY"  # S&P 500 proxy for market alerts


class PriceProvider(Protocol):
    def daily_returns(self, tickers: list[str], start: date, end: date | None = None) -> Returns: ...


def get_provider(name: str | None = None) -> PriceProvider:
    name = name or config.PRICE_PROVIDER
    if name == "yfinance_dev":
        from tracker.data.providers.yfinance_dev import YFinanceDev

        return YFinanceDev()
    raise ValueError(f"Unknown PRICE_PROVIDER {name!r}")


def store_returns(session: Session, returns: Returns) -> int:
    """Upsert daily returns. Works on SQLite and Postgres."""
    rows = [
        {"ticker": t, "date": d, "return_pct": pct}
        for t, series in returns.items()
        for d, pct in series
    ]
    if not rows:
        return 0
    dialect = session.get_bind().dialect.name
    ins = (postgresql if dialect == "postgresql" else sqlite).insert(DailyReturn)
    stmt = ins.on_conflict_do_update(
        index_elements=["ticker", "date"], set_={"return_pct": ins.excluded.return_pct}
    )
    session.execute(stmt, rows)
    return len(rows)
