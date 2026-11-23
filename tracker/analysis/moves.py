"""Move detection and the attribution ladder (AGENTS.md rule 14). Numbers only; no searches, no model calls.

For one trading day: the S&P 500 (SPY) level (none / alert / major), then each covered stock that moved at
least MOVE_THRESHOLD_PCT (DEMO_MOVE_THRESHOLD_PCT for demo stocks) gets a scope:
- market:   the market alert is on and the stock differs from the index by less than RESIDUAL_PCT;
- industry: at least INDUSTRY_MIN_PEERS tracked peers in its industry average a move of at least
            INDUSTRY_MOVE_PCT, and the stock differs from that average by less than RESIDUAL_PCT;
- stock:    otherwise.
The scope decides what gets searched: one market note, one note per industry, or one note per stock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from statistics import mean
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker import config
from tracker.data.prices import MARKET_TICKER
from tracker.models import DailyReturn, MarketDay, Move, Universe

Level = Literal["none", "alert", "major"]
Scope = Literal["market", "industry", "stock"]


def market_level(index_return_pct: float) -> Level:
    a = abs(index_return_pct)
    if a >= config.MARKET_MAJOR_PCT:
        return "major"
    if a >= config.MARKET_ALERT_PCT:
        return "alert"
    return "none"


@dataclass(frozen=True)
class Classified:
    ticker: str
    return_pct: float
    scope: Scope
    market_return_pct: float
    industry: str
    industry_return_pct: float | None  # average of tracked peers (the stock itself excluded); None if too few


def peer_average(ticker: str, industry: str, returns: dict[str, float], industries: dict[str, str]) -> float | None:
    peers = [r for t, r in returns.items() if t != ticker and industries.get(t) == industry]
    return mean(peers) if len(peers) >= config.INDUSTRY_MIN_PEERS else None


def is_candidate(ticker: str, return_pct: float, demo: set[str]) -> bool:
    threshold = config.DEMO_MOVE_THRESHOLD_PCT if ticker in demo else config.MOVE_THRESHOLD_PCT
    return abs(return_pct) >= threshold


def classify(ticker: str, return_pct: float, index_return_pct: float, returns: dict[str, float],
             industries: dict[str, str]) -> Classified:
    industry = industries.get(ticker, "")
    peers = peer_average(ticker, industry, returns, industries)
    if market_level(index_return_pct) != "none" and abs(return_pct - index_return_pct) < config.RESIDUAL_PCT:
        scope: Scope = "market"
    elif (peers is not None and abs(peers) >= config.INDUSTRY_MOVE_PCT
          and abs(return_pct - peers) < config.RESIDUAL_PCT):
        scope = "industry"
    else:
        scope = "stock"
    return Classified(ticker, return_pct, scope, index_return_pct, industry, peers)


def classify_day(returns: dict[str, float], index_return_pct: float, industries: dict[str, str],
                 covered: set[str], demo: set[str]) -> list[Classified]:
    """Candidates among covered stocks, each with its scope. `returns` holds every tracked stock (peers count
    even when nobody follows them); only covered stocks become moves (rule 8)."""
    out = [classify(t, r, index_return_pct, returns, industries)
           for t, r in sorted(returns.items()) if t in covered and is_candidate(t, r, demo)]
    return out


def industry_average(industry: str, returns: dict[str, float], industries: dict[str, str]) -> float | None:
    """Average of every tracked stock in the industry: the number shown in a shared industry note."""
    rs = [r for t, r in returns.items() if industries.get(t) == industry]
    return mean(rs) if rs else None


# ---- database -------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Day:
    date: date
    index_return_pct: float
    level: Level
    moves: list[Classified]
    returns: dict[str, float]
    industries: dict[str, str]


def load_day(session: Session, day: date, covered: set[str]) -> Day | None:
    """Classify one trading day from daily_returns. None when SPY has no return for that day."""
    spy = session.scalar(select(DailyReturn.return_pct).where(DailyReturn.ticker == MARKET_TICKER,
                                                             DailyReturn.date == day))
    if spy is None:
        return None
    rows = session.execute(select(DailyReturn.ticker, DailyReturn.return_pct, Universe.industry, Universe.is_demo)
                           .join(Universe, Universe.ticker == DailyReturn.ticker)
                           .where(DailyReturn.date == day, Universe.active)).all()
    returns = {t: float(r) for t, r, _, _ in rows}
    industries = {t: ind for t, _, ind, _ in rows}
    demo = {t for t, _, _, is_demo in rows if is_demo}
    moves = classify_day(returns, float(spy), industries, covered, demo)
    return Day(day, float(spy), market_level(float(spy)), moves, returns, industries)


def record_day(session: Session, d: Day, now: datetime | None = None) -> list[Move]:
    """Upsert market_days and moves (status pending). A move already explained keeps its note and status."""
    now = now or datetime.now()
    md = session.get(MarketDay, d.date) or MarketDay(date=d.date)
    md.index_return_pct, md.level = d.index_return_pct, d.level
    session.add(md)
    existing = {m.ticker: m for m in session.scalars(select(Move).where(Move.date == d.date))}
    out = []
    for c in d.moves:
        m = existing.get(c.ticker)
        if m is None:
            m = Move(ticker=c.ticker, date=d.date, status="pending")
            session.add(m)
        m.return_pct, m.scope = c.return_pct, c.scope
        m.market_return_pct, m.industry_return_pct = c.market_return_pct, c.industry_return_pct
        out.append(m)
    session.flush()
    return out
