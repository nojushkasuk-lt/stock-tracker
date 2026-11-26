"""Sudden-move alerts during the session (every 15 minutes: Cloud Scheduler runs this as a Cloud Run job).

Uses the transient Tiingo snapshot as an internal trigger only: the alert says which way a stock is moving
("moving sharply lower") and links to the stock page, where TradingView shows the live quote. No Tiingo price
or percentage is shown, emailed or stored. The closing-news job explains the moves after the close.
"""

import argparse
from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from tracker import accounts, config
from tracker.alerts import email_pending
from tracker.data.providers import tiingo
from tracker.db import create_tables, session_scope
from tracker.models import Universe, UserWatchlist

OPEN, CLOSE = time(9, 45), time(16, 5)  # skip the first minutes: pre-market quotes can linger in the snapshot
MAX_QUOTE_AGE = timedelta(minutes=45)


def market_hours(now: datetime) -> bool:
    return now.weekday() < 5 and OPEN <= now.time() <= CLOSE


def _direction(change: float) -> str:
    return "higher" if change > 0 else "lower"


def notify(s, changes: dict[str, tuple[float, datetime, date]], now: datetime) -> int:
    """Add in-site alerts for followers (per user threshold) and for sharp S&P 500 moves. Idempotent per day."""
    fresh = {t: c for t, c in changes.items() if now - c[1] <= MAX_QUOTE_AGE and c[2] == now.date()}
    names = dict(s.execute(select(Universe.ticker, Universe.name)).all())
    spotted = now.strftime("%H:%M").lstrip("0")
    day = now.date().isoformat()
    added = 0
    for email in sorted(set(s.scalars(select(UserWatchlist.email)))):
        p = accounts.prefs(s, email)
        if p.market_alerts and "SPY" in fresh and abs(fresh["SPY"][0]) >= config.MARKET_ALERT_PCT:
            added += accounts.notify(
                s, email, kind="market_intraday", url="/movers", dedupe_key=f"intraday-market:{day}",
                title=f"The S&P 500 is moving sharply {_direction(fresh['SPY'][0])} today",
                body=f"Spotted at {spotted} New York time. Live quotes are on the Movers page; "
                     "the market note follows after the close.")
        if not p.stock_alerts:
            continue
        for t in accounts.watchlist(s, email):
            if t in fresh and abs(fresh[t][0]) >= float(p.alert_threshold_pct):
                added += accounts.notify(
                    s, email, kind="stock_intraday", ticker=t, url=f"/stock/{t}",
                    dedupe_key=f"intraday:{t}:{day}",
                    title=f"{names.get(t, t)} is moving sharply {_direction(fresh[t][0])} today",
                    body=f"Spotted at {spotted} New York time. The live quote and coverage are on the stock page; "
                         "the closing news explains the move after the close.")
    return added


def main(force: bool = False) -> None:
    if not config.TIINGO_API_KEY:
        raise SystemExit("Move alerts need TIINGO_API_KEY.")
    now = datetime.now(tiingo.NEW_YORK)
    if not (force or market_hours(now)):
        print(f"{now:%a %H:%M} New York: market closed, nothing to check.")
        return
    create_tables()
    with session_scope() as s:
        followed = sorted(set(s.scalars(select(UserWatchlist.ticker))))
        changes = tiingo.intraday_changes([*followed, "SPY"])
        if not changes:
            print("No snapshot (Tiingo unavailable or market holiday).")
            return
        print(f"{now:%H:%M}: {notify(s, changes, now)} new alerts "
              f"for {len(followed)} followed stocks.")
        email_pending(s)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Run outside market hours (testing)")
    main(parser.parse_args().force)
