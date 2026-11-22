"""Daily job. For now: load the universe and refresh daily returns. Filings, news and moves come later."""

from datetime import date, timedelta

from sqlalchemy import select

from tracker.data.edgar import EdgarClient
from tracker.data.fundamentals import refresh_fundamentals
from tracker.data.prices import MARKET_TICKER, get_provider, store_returns
from tracker.data.universe import load_universe
from tracker.db import create_tables, session_scope
from tracker.models import Universe


def main(years: int = 5) -> None:
    create_tables()
    with session_scope() as s:
        n = load_universe(s)
        print(f"universe: {n} rows")
        tickers = list(s.scalars(select(Universe.ticker))) + [MARKET_TICKER]
        start = date.today() - timedelta(days=365 * years + 5)
        returns = get_provider().daily_returns(tickers, start)
        missing = sorted(set(tickers) - set(returns))
        stored = store_returns(s, returns)
        fetched = refresh_fundamentals(s, EdgarClient())  # only companies with no figures yet; Day 3 makes this filing-triggered
        print(f"fundamentals: fetched {len(fetched)} new companies")
        print(f"daily_returns: {stored} rows for {len(returns)}/{len(tickers)} tickers; no data for: {missing}")


if __name__ == "__main__":
    main()
