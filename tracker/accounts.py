"""Users, their watchlists and outlet choices, and the per-user caps (AGENTS.md rules 6 and 8).

Days and months are UTC calendar days and months. Every refresh or "more coverage" request is logged in
refresh_requests with its outcome, and the caps are counted from that table.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Callable, Literal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from tracker import config
from tracker.data.news import load_outlets
from tracker.models import (Notification, RefreshRequest, ShareLink, Universe, User, UserMarket, UserOutlet, UserPrefs,
                            UserWatchlist)


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start(now: datetime) -> datetime:
    return _day_start(now).replace(day=1)


# ---- users ----------------------------------------------------------------------------------------

def normalize_email(email: str) -> str:
    email = (email or "").strip().lower()
    if "@" not in email:
        raise ValueError("not an email address")
    return email


def ensure_user(session: Session, email: str, now: datetime | None = None) -> User:
    """Create the user on first sign-in; update last_login on every sign-in."""
    now = now or utcnow()
    email = normalize_email(email)
    u = session.get(User, email)
    if u is None:
        u = User(email=email, created_at=now)
        session.add(u)
    u.last_login = now
    session.flush()
    return u


# ---- watchlist ------------------------------------------------------------------------------------

class WatchlistError(ValueError):
    pass


def watchlist(session: Session, email: str) -> list[str]:
    q = select(UserWatchlist.ticker).where(UserWatchlist.email == normalize_email(email)).order_by(UserWatchlist.added_at, UserWatchlist.ticker)
    return list(session.scalars(q))


def set_watchlist(session: Session, email: str, tickers: list[str], now: datetime | None = None) -> list[str]:
    """Replace the user's watchlist. At most WATCHLIST_MAX stocks from the universe. A stock that left the
    top 100 (active = FALSE) may be kept by someone who already follows it, but nobody new can add it."""
    now = now or utcnow()
    email = normalize_email(email)
    wanted = list(dict.fromkeys(t.strip().upper() for t in tickers if t.strip()))
    if len(wanted) > config.WATCHLIST_MAX:
        raise WatchlistError(f"You can follow at most {config.WATCHLIST_MAX} stocks.")
    current = set(watchlist(session, email))
    rows = {u.ticker: u for u in session.scalars(select(Universe).where(Universe.ticker.in_(wanted)))}
    unknown = [t for t in wanted if t not in rows]
    if unknown:
        raise WatchlistError(f"Not in the list of followable stocks: {', '.join(unknown)}")
    closed = [t for t in wanted if not rows[t].active and t not in current]
    if closed:
        raise WatchlistError(f"No longer in the top 100, so it can't be added: {', '.join(closed)}")
    session.execute(delete(UserWatchlist).where(UserWatchlist.email == email, UserWatchlist.ticker.notin_(wanted)))
    for t in wanted:
        if t not in current:
            session.add(UserWatchlist(email=email, ticker=t, added_at=now))
    session.flush()
    return watchlist(session, email)


# ---- outlets --------------------------------------------------------------------------------------

def outlets(session: Session, email: str) -> set[str]:
    """Chosen outlet domains; empty means all outlets."""
    return set(session.scalars(select(UserOutlet.domain).where(UserOutlet.email == normalize_email(email))))


def set_outlets(session: Session, email: str, domains: list[str]) -> set[str]:
    email = normalize_email(email)
    known = {o.domain for o in load_outlets()}
    bad = sorted(set(domains) - known)
    if bad:
        raise ValueError(f"unknown outlets: {bad}")
    session.execute(delete(UserOutlet).where(UserOutlet.email == email))
    for d in sorted(set(domains)):
        session.add(UserOutlet(email=email, domain=d))
    session.flush()
    return outlets(session, email)


# ---- caps -----------------------------------------------------------------------------------------

Kind = Literal["refresh", "coverage_search"]


def _count(session: Session, kind: Kind, since: datetime, email: str | None = None, ticker: str | None = None,
           statuses: tuple[str, ...] = ("done",)) -> int:
    q = select(func.count()).select_from(RefreshRequest).where(
        RefreshRequest.kind == kind, RefreshRequest.requested_at >= since, RefreshRequest.status.in_(statuses))
    if email:
        q = q.where(RefreshRequest.email == email)
    if ticker:
        q = q.where(RefreshRequest.ticker == ticker)
    return session.scalar(q) or 0


def _log(session: Session, email: str, ticker: str, kind: Kind, status: str, now: datetime) -> None:
    session.add(RefreshRequest(email=email, ticker=ticker, kind=kind, requested_at=now, status=status))
    session.flush()


@dataclass(frozen=True)
class RefreshOutcome:
    status: str     # served_from_cache, done, refused_cap, failed
    message: str


def refreshes_left_today(session: Session, email: str, now: datetime | None = None) -> int:
    now = now or utcnow()
    used = _count(session, "refresh", _day_start(now), email=normalize_email(email))
    return max(0, config.REFRESH_PER_USER_PER_DAY - used)


def request_refresh(session: Session, email: str, ticker: str, do_refresh: Callable[[], bool],
                    now: datetime | None = None) -> RefreshOutcome:
    """Rate-limited "Refresh now". do_refresh() does the work (search + note) and returns True on success.

    Order: a refresh of this ticker by anyone in the last REFRESH_SHARE_HOURS is shared (free, no call);
    then the user's daily cap; then the monthly total. Only successful refreshes count toward the caps."""
    now = now or utcnow()
    email, ticker = normalize_email(email), ticker.upper()
    if _count(session, "refresh", now - timedelta(hours=config.REFRESH_SHARE_HOURS), ticker=ticker):
        _log(session, email, ticker, "refresh", "served_from_cache", now)
        return RefreshOutcome("served_from_cache", f"{ticker} was refreshed in the last "
                              f"{config.REFRESH_SHARE_HOURS:g} hours. You're seeing the latest note.")
    if _count(session, "refresh", _day_start(now), email=email) >= config.REFRESH_PER_USER_PER_DAY:
        _log(session, email, ticker, "refresh", "refused_cap", now)
        return RefreshOutcome("refused_cap", f"You've used your {config.REFRESH_PER_USER_PER_DAY} refreshes for "
                              "today. They reset at midnight UTC.")
    if _count(session, "refresh", _month_start(now)) >= config.REFRESH_PER_MONTH:
        _log(session, email, ticker, "refresh", "refused_cap", now)
        return RefreshOutcome("refused_cap", "The site has reached its refresh limit for this month.")
    try:
        ok = do_refresh()
    except Exception:
        ok = False
    _log(session, email, ticker, "refresh", "done" if ok else "failed", now)
    return RefreshOutcome("done", "Refreshed.") if ok else RefreshOutcome("failed", "Refresh failed. Try again later.")


def coverage_searches_left_today(session: Session, email: str, now: datetime | None = None) -> int:
    now = now or utcnow()
    used = _count(session, "coverage_search", _day_start(now), email=normalize_email(email))
    return max(0, config.COVERAGE_SEARCHES_PER_USER_PER_DAY - used)


def use_coverage_search(session: Session, email: str, ticker: str, now: datetime | None = None) -> bool:
    """Count one "more coverage" search. False (and logged as refused) when the daily cap is used up."""
    now = now or utcnow()
    email = normalize_email(email)
    if coverage_searches_left_today(session, email, now) <= 0:
        _log(session, email, ticker.upper(), "coverage_search", "refused_cap", now)
        return False
    _log(session, email, ticker.upper(), "coverage_search", "done", now)
    return True


# ---- start dates (performance "since you started") -------------------------------------------------

def start_dates(session: Session, email: str) -> dict[str, date]:
    """{ticker: date performance is measured from}: the chosen start date, else the day it was added."""
    rows = session.execute(select(UserWatchlist.ticker, UserWatchlist.start_date, UserWatchlist.added_at)
                           .where(UserWatchlist.email == normalize_email(email))).all()
    return {t: (sd or added.date()) for t, sd, added in rows}


def set_start_date(session: Session, email: str, ticker: str, start: date | None, now: datetime | None = None) -> None:
    """None resets to the day the stock was added. Future dates and dates before 1990 are refused."""
    now = now or utcnow()
    if start is not None and (start > now.date() or start.year < 1990):
        raise WatchlistError("Pick a start date between 1990 and today.")
    row = session.get(UserWatchlist, (normalize_email(email), ticker.upper()))
    if row is None:
        raise WatchlistError("Follow the stock first.")
    row.start_date = start
    session.flush()


# ---- markets (index funds / ETFs) ----------------------------------------------------------------------

MARKETS_MAX = 12


def followed_markets(session: Session, email: str) -> list[str]:
    q = select(UserMarket.ticker).where(UserMarket.email == normalize_email(email)).order_by(UserMarket.added_at, UserMarket.ticker)
    return list(session.scalars(q))


def set_markets(session: Session, email: str, tickers: list[str], now: datetime | None = None) -> list[str]:
    from tracker.data import markets

    now = now or utcnow()
    email = normalize_email(email)
    known = set(markets.tickers())
    wanted = list(dict.fromkeys(t.strip().upper() for t in tickers if t.strip()))
    unknown = [t for t in wanted if t not in known]
    if unknown:
        raise WatchlistError(f"Unknown market: {', '.join(unknown)}")
    if len(wanted) > MARKETS_MAX:
        raise WatchlistError(f"You can follow at most {MARKETS_MAX} markets.")
    current = set(followed_markets(session, email))
    session.execute(delete(UserMarket).where(UserMarket.email == email, UserMarket.ticker.notin_(wanted)))
    for t in wanted:
        if t not in current:
            session.add(UserMarket(email=email, ticker=t, added_at=now))
    session.flush()
    return followed_markets(session, email)


# ---- preferences and onboarding --------------------------------------------------------------------------

PREF_CHOICES = {"digest": ("off", "daily", "weekly"), "home": ("portfolio", "market", "news"),
                "perf_basis": ("start", "1D", "1M", "1Y")}
THRESHOLDS = (3.0, 4.0, 5.0, 7.5, 10.0)


def prefs(session: Session, email: str) -> UserPrefs:
    """The user's preferences (defaults when none saved yet; nothing is written)."""
    row = session.get(UserPrefs, normalize_email(email))
    return row or UserPrefs(email=normalize_email(email), onboarded_at=None, stock_alerts=True, market_alerts=True,
                            alert_threshold_pct=5.0, email_alerts=False, digest="weekly", home="portfolio", perf_basis="start")


def set_prefs(session: Session, email: str, **values) -> UserPrefs:
    email = normalize_email(email)
    row = session.get(UserPrefs, email)
    if row is None:
        row = prefs(session, email)
        session.add(row)
    for k, v in values.items():
        if k in PREF_CHOICES and v not in PREF_CHOICES[k]:
            raise ValueError(f"{k} must be one of {PREF_CHOICES[k]}")
        if k == "alert_threshold_pct" and float(v) not in THRESHOLDS:
            raise ValueError(f"alert_threshold_pct must be one of {THRESHOLDS}")
        if k not in {"onboarded_at", "stock_alerts", "market_alerts", "alert_threshold_pct", "email_alerts", *PREF_CHOICES}:
            raise ValueError(f"Unknown preference {k}")
        setattr(row, k, v)
    session.flush()
    return row


def needs_onboarding(session: Session, email: str) -> bool:
    row = session.get(UserPrefs, normalize_email(email))
    return row is None or row.onboarded_at is None


# ---- notifications ---------------------------------------------------------------------------------------

def notify(session: Session, email: str, *, kind: str, title: str, body: str, url: str, dedupe_key: str,
           ticker: str | None = None, now: datetime | None = None) -> bool:
    """Add an in-site alert unless the same one (dedupe_key) exists. Returns True when added."""
    email = normalize_email(email)
    exists = session.scalar(select(Notification.id).where(Notification.email == email, Notification.dedupe_key == dedupe_key))
    if exists:
        return False
    session.add(Notification(email=email, kind=kind, ticker=ticker, title=title, body=body, url=url,
                             dedupe_key=dedupe_key, created_at=now or utcnow()))
    session.flush()
    return True


def notifications(session: Session, email: str, limit: int = 30) -> list[Notification]:
    q = (select(Notification).where(Notification.email == normalize_email(email))
         .order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit))
    return list(session.scalars(q))


def unread_count(session: Session, email: str) -> int:
    return int(session.scalar(select(func.count()).select_from(Notification)
                              .where(Notification.email == normalize_email(email), Notification.read_at.is_(None))) or 0)


def mark_read(session: Session, email: str, now: datetime | None = None) -> None:
    from sqlalchemy import update

    session.execute(update(Notification).where(Notification.email == normalize_email(email), Notification.read_at.is_(None))
                    .values(read_at=now or utcnow()))


# ---- share links (private access) ---------------------------------------------------------------------------

def create_share_link(session: Session, label: str, now: datetime | None = None) -> ShareLink:
    import secrets

    row = ShareLink(token=secrets.token_urlsafe(18), label=label.strip()[:80] or "Shared link", created_at=now or utcnow(), uses=0)
    session.add(row)
    session.flush()
    return row


def use_share_link(session: Session, token: str, now: datetime | None = None) -> bool:
    row = session.get(ShareLink, token)
    if row is None or row.revoked_at is not None:
        return False
    row.uses = (row.uses or 0) + 1
    row.last_used_at = now or utcnow()
    session.flush()
    return True


def share_link_valid(session: Session, token: str | None) -> bool:
    if not token:
        return False
    row = session.get(ShareLink, token)
    return row is not None and row.revoked_at is None


def share_links(session: Session) -> list[ShareLink]:
    return list(session.scalars(select(ShareLink).order_by(ShareLink.created_at.desc())))


def revoke_share_link(session: Session, token: str, now: datetime | None = None) -> None:
    row = session.get(ShareLink, token)
    if row is not None and row.revoked_at is None:
        row.revoked_at = now or utcnow()
        session.flush()
