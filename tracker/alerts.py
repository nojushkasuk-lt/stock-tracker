"""In-site alerts for followers: big moves in their stocks and sharp market moves (written by jobs/daily.py)."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker import accounts, config
from tracker.models import AiOutput, DailyReturn, MarketDay, Move, UserWatchlist


def notify_followers(s: Session, day: date | None = None) -> int:
    """Create in-site alerts for the latest trading day: big moves in followed stocks (per user threshold) and
    sharp market moves. Idempotent (dedupe keys). Returns the number of alerts added. Called by jobs/daily.py after the move notes."""
    added = 0
    md = s.get(MarketDay, day) if day else s.scalars(select(MarketDay).order_by(MarketDay.date.desc())).first()
    if md is None:
        return 0
    day = md.date
    users = sorted(set(s.scalars(select(UserWatchlist.email))))
    if config.PRICE_DATA_DISPLAY != "all":  # alerts are provider moves: owner only until licensed (rule 13)
        users = [u for u in users if config.OWNER_EMAIL and u.lower() == config.OWNER_EMAIL.lower()]
    for email in users:
        p = accounts.prefs(s, email)
        if p.market_alerts and md.level != "none":
            verb = "fell" if md.index_return_pct < 0 else "rose"
            added += accounts.notify(
                s, email, kind="market", title=f"S&P 500 {verb} {abs(float(md.index_return_pct)):.1f}%",
                body="Sharp market move. The market note explains what coverage points to.", url="/market",
                dedupe_key=f"market:{day.isoformat()}")
        if not p.stock_alerts:
            continue
        mine = accounts.watchlist(s, email)
        for t, r in s.execute(select(DailyReturn.ticker, DailyReturn.return_pct)
                              .where(DailyReturn.ticker.in_(mine), DailyReturn.date == day)).all():
            if abs(float(r)) < float(p.alert_threshold_pct):
                continue
            mv = s.scalars(select(Move).where(Move.ticker == t, Move.date == day)).first()
            note = s.get(AiOutput, mv.note_id) if mv is not None and mv.note_id else None
            body = (note.content.get("summary") if note else None) or "No note yet. It is written after the daily check."
            added += accounts.notify(
                s, email, kind="stock", ticker=t, title=f"{t} {'fell' if r < 0 else 'rose'} {abs(float(r)):.1f}%",
                body=body, url=f"/stock/{t}", dedupe_key=f"move:{t}:{day.isoformat()}")
    return added


def send_emails(s: Session, sender, now=None, max_age_days: int = 2) -> int:
    """Email unsent alerts to users who turned email alerts on: one email per user per run, newest first.
    Older alerts (or users with email off) are marked as handled without sending. Returns emails sent."""
    from datetime import datetime, timedelta, UTC

    from tracker import config
    from tracker.emailer import Item, compose
    from tracker.models import Notification

    now = now or datetime.now(UTC).replace(tzinfo=None)
    pending = s.scalars(select(Notification).where(Notification.emailed_at.is_(None))
                        .order_by(Notification.email, Notification.created_at.desc())).all()
    by_user: dict[str, list] = {}
    for n in pending:
        by_user.setdefault(n.email, []).append(n)
    sent = 0
    for email, items in by_user.items():
        fresh = [n for n in items if n.created_at >= now - timedelta(days=max_age_days)]
        if accounts.prefs(s, email).email_alerts and fresh:
            shown = fresh[: config.EMAIL_MAX_ITEMS]
            msg = compose(email, [Item(n.title, n.body, config.BASE_URL + n.url) for n in shown], more=len(fresh) - len(shown))
            sender.send(msg)
            sent += 1
        for n in items:
            n.emailed_at = now
        s.flush()
    return sent


def email_pending(s: Session) -> None:
    """Send waiting alert emails (one per user per run). Never fails the calling job: alerts stay on the site."""
    from tracker.emailer import GmailSender

    if not config.email_ready():
        print("email: off (not configured)")
        return
    try:
        with GmailSender() as g:
            print(f"email: {send_emails(s, g)} sent")
    except Exception as e:
        print(f"email: FAILED {type(e).__name__}")
