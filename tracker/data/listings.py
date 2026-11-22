"""Spot new exchange listings (IPOs) from the SEC ticker file so they can enter the ranking within a week."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker.data.edgar import EdgarClient, is_domestic_filer
from tracker.models import ListingSeen

EXCHANGES = {"Nasdaq", "NYSE", "CBOE"}


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def discover_new_listings(session: Session, edgar: EdgarClient, known: set[str]) -> list[str]:
    """Record every listed ticker; flag brand-new US domestic filers as candidates.

    The first run only records a baseline (everything is "seen", nothing is new).
    Returns the tickers newly flagged as candidates.
    """
    rows = [r for r in edgar.tickers_exchange() if r.get("exchange") in EXCHANGES and r.get("ticker")]
    seen = set(session.scalars(select(ListingSeen.ticker)))
    now = _now()
    baseline = not seen
    flagged: list[str] = []
    for r in rows:
        t = r["ticker"].upper()
        if t in seen:
            continue
        is_cand, sic = False, None
        if not baseline and t not in known:
            sub = edgar.submissions(r["cik"])
            if is_domestic_filer(sub):
                is_cand, sic = True, sub.get("sic") or None
                flagged.append(t)
        session.add(ListingSeen(ticker=t, cik=str(r["cik"]).zfill(10), name=r["name"], exchange=r["exchange"],
                                sic_code=sic, is_candidate=is_cand, first_seen=now))
        seen.add(t)
    session.flush()
    return sorted(flagged)


def discovered_candidates(session: Session) -> list[dict]:
    return [
        {"ticker": l.ticker, "cik": l.cik, "name": l.name, "industry": "", "sic_code": l.sic_code}
        for l in session.scalars(select(ListingSeen).where(ListingSeen.is_candidate))
    ]
