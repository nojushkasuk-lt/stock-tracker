"""Follower alerts from the daily job: per-user threshold, market alerts, no duplicates."""

from datetime import date, datetime

from test_llm import db  # noqa: F401
from tracker import accounts
from tracker.alerts import notify_followers
from tracker.models import DailyReturn, MarketDay, Universe

DAY = date(2026, 11, 20)
NOW = datetime(2026, 11, 20, 22)


def _setup(db):
    for t in ("AAA", "BBB"):
        db.add(Universe(ticker=t, cik="1", name=t, industry="X", market_cap_rank=1, is_demo=False, active=True, updated_at=NOW))
    db.flush()
    db.add_all([DailyReturn(ticker="AAA", date=DAY, return_pct=-6.2), DailyReturn(ticker="BBB", date=DAY, return_pct=3.5),
                MarketDay(date=DAY, index_return_pct=-2.4, level="alert")])
    accounts.ensure_user(db, "a@x.com", NOW); accounts.ensure_user(db, "b@x.com", NOW)
    accounts.set_watchlist(db, "a@x.com", ["AAA", "BBB"], NOW)
    accounts.set_watchlist(db, "b@x.com", ["BBB"], NOW)
    db.flush()


def test_alerts_use_each_users_threshold_and_are_not_repeated(db):
    _setup(db)
    accounts.set_prefs(db, "b@x.com", alert_threshold_pct=3.0, market_alerts=False)
    assert notify_followers(db) == 3  # a: AAA + market; b: BBB (3% threshold), no market alert
    a = {n.title for n in accounts.notifications(db, "a@x.com")}
    assert a == {"AAA fell 6.2%", "S&P 500 fell 2.4%"}
    assert [n.title for n in accounts.notifications(db, "b@x.com")] == ["BBB rose 3.5%"]
    assert notify_followers(db) == 0


def test_stock_alerts_can_be_turned_off(db):
    _setup(db)
    accounts.set_prefs(db, "a@x.com", stock_alerts=False)
    assert {n.kind for n in (notify_followers(db) and accounts.notifications(db, "a@x.com"))} == {"market"}


class FakeSender:
    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)


def test_emails_go_only_to_users_who_turned_them_on_once(db, monkeypatch):
    from tracker import config
    from tracker.alerts import send_emails
    monkeypatch.setattr(config, "SMTP_USER", "alerts@example.com")
    monkeypatch.setattr(config, "BASE_URL", "https://site.example")
    _setup(db)
    accounts.set_prefs(db, "a@x.com", email_alerts=True)
    accounts.set_prefs(db, "b@x.com", alert_threshold_pct=3.0)  # email off
    notify_followers(db)
    f = FakeSender()
    assert send_emails(db, f, now=NOW) == 1
    [msg] = f.sent
    assert msg["To"] == "a@x.com" and "2 new alerts" in msg["Subject"]
    assert "https://site.example/stock/AAA" in msg.get_body(("plain",)).get_content()
    assert send_emails(db, f, now=NOW) == 0  # every alert is handled once, sent or not


def test_email_html_escapes_note_text():
    from tracker.emailer import Item, compose
    msg = compose("a@x.com", [Item("AAA fell 6.2%", "<script>x</script> & more", "https://s/stock/AAA")])
    html = msg.get_body(("html",)).get_content()
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "Not investment advice" in html and "settings#alerts" in html
