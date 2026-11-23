"""Daily job after the US close: returns, filings, figures, then moves and their notes.

python -m jobs.daily             full run
python -m jobs.daily --recheck   only recheck moves that had no catalyst (rule 14: 6-12 hours later)
"""

import argparse
from datetime import date, timedelta

from sqlalchemy import func, select

from tracker.ai.notes import explain_day
from tracker.analysis import moves
from tracker.data import news
from tracker.data.edgar import EdgarClient
from tracker.data.filing_text import FilingFetcher
from tracker.data.filings import check_filings, needs_new_figures
from tracker.data.fundamentals import refresh_fundamentals
from tracker.data.markets import tickers as market_tickers
from tracker.data.prices import MARKET_TICKER, get_provider, store_returns
from tracker.data.universe import covered_tickers, load_universe
from tracker.db import create_tables, session_scope
from tracker.models import DailyReturn, Move, Universe


def explain_moves(s, edgar: EdgarClient, recheck_only: bool = False) -> None:
    try:
        brave = news.BraveNews()
    except news.NewsNotConfigured as e:
        print(f"moves: skipped ({e})")
        return
    fetcher = FilingFetcher(edgar)
    if recheck_only:
        days = sorted(set(s.scalars(select(Move.date).where(Move.status == "recheck"))))
    else:
        last = s.scalar(select(func.max(DailyReturn.date)).where(DailyReturn.ticker == MARKET_TICKER))
        days = [last] if last else []
    covered = covered_tickers(s)
    for day in days:
        d = moves.load_day(s, day, covered)
        if d is None:
            continue
        if not recheck_only:
            moves.record_day(s, d)
        rep = explain_day(s, d, brave, fetcher, only_pending=recheck_only)
        scopes = {c.scope for c in d.moves}
        print(f"moves {day}: S&P 500 {d.index_return_pct:+.1f}% ({d.level}), {len(d.moves)} moves {sorted(scopes)}; "
              f"notes {rep.notes}" + (f"; STOPPED {rep.stopped}" if rep.stopped else ""))
        if rep.stopped:
            break


def main(years: int = 5, recheck_only: bool = False) -> None:
    create_tables()
    with session_scope() as s:
        edgar = EdgarClient()
        if recheck_only:
            explain_moves(s, edgar, recheck_only=True)
            return
        n = load_universe(s)
        print(f"universe: {n} new rows")
        tickers = sorted(set(s.scalars(select(Universe.ticker))) | {MARKET_TICKER} | set(market_tickers()))
        start = date.today() - timedelta(days=365 * years + 5)
        returns = get_provider().daily_returns(tickers, start)
        missing = sorted(set(tickers) - set(returns))
        stored = store_returns(s, returns)
        new = check_filings(s, edgar)
        print(f"filings: new for {sorted(new)}")
        updated = needs_new_figures(new)  # a new 10-Q / 10-K means new XBRL figures
        if updated:
            refresh_fundamentals(s, edgar, updated, only_missing=False)
        fetched = refresh_fundamentals(s, edgar)  # companies with no figures yet (e.g. new entrants)
        print(f"fundamentals: refreshed {updated}, fetched {len(fetched)} new companies")
        print(f"daily_returns: {stored} rows for {len(returns)}/{len(tickers)} tickers; no data for: {missing}")
        explain_moves(s, edgar)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--recheck", action="store_true", help="only recheck moves with no catalyst yet")
    main(recheck_only=ap.parse_args().recheck)
