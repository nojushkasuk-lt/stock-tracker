"""Sudden-move alerts: Tiingo snapshot as an internal trigger; alerts and the Movers page show direction only."""

import re
from datetime import datetime

import pytest
from sqlalchemy import select

from jobs import intraday_alerts
from tests.test_tiingo import _row, snapshot  # noqa: F401  (fixture)
from tests.test_web import client, sign_in  # noqa: F401  (fixture)
from tracker import accounts, config, services
from tracker.data.providers import tiingo
from tracker.models import Notification

NOW = datetime(2026, 11, 25, 11, 15, tzinfo=tiingo.NEW_YORK)


def test_sharp_moves_give_direction_only_for_the_latest_session(snapshot):
    snapshot += [_row("AAPL", 106.0, 100.0), _row("MSFT", 98.0, 100.0), _row("BRK-B", 90.0, 100.0),
                 _row("OLD", 150.0, 100.0, ts="2026-11-20T15:00:00-05:00", prev_date="2026-11-19")]
    snap = tiingo.sharp_moves({"AAPL": 5.0, "MSFT": 5.0, "BRK-B": 5.0, "OLD": 5.0})
    assert {t: m.direction for t, m in snap.moves.items()} == {"AAPL": "rose", "BRK-B": "fell"}
    assert snap.session.isoformat() == "2026-11-25" and snap.as_of is not None
    assert not any(isinstance(v, float) for m in snap.moves.values() for v in vars(m).values())
    assert tiingo.sharp_moves({"MSFT": 2.0}).moves["MSFT"].direction == "fell"  # per-stock threshold


def test_market_hours():
    assert intraday_alerts.market_hours(NOW)
    assert not intraday_alerts.market_hours(NOW.replace(hour=9, minute=35))
    assert not intraday_alerts.market_hours(NOW.replace(hour=17))
    assert not intraday_alerts.market_hours(datetime(2026, 11, 28, 11, 0, tzinfo=tiingo.NEW_YORK))  # Saturday


def test_followers_get_one_qualitative_alert_per_stock_per_day(client):
    with services.session_scope() as s:
        for e in ("a@example.com", "b@example.com"):
            accounts.ensure_user(s, e)
        accounts.set_watchlist(s, "a@example.com", ["AAPL", "MSFT"])
        accounts.set_watchlist(s, "b@example.com", ["AAPL"])
        accounts.set_prefs(s, "b@example.com", alert_threshold_pct=10.0, market_alerts=False)
        changes = {"AAPL": (-7.3, NOW, NOW.date()), "MSFT": (4.0, NOW, NOW.date()), "SPY": (-2.4, NOW, NOW.date())}
        assert intraday_alerts.notify(s, changes, NOW) == 2  # a: AAPL + market; b: below 10%, market off
        assert intraday_alerts.notify(s, changes, NOW) == 0  # idempotent within the day
        rows = s.scalars(select(Notification).order_by(Notification.id)).all()
        assert [(n.email, n.title) for n in rows] == [
            ("a@example.com", "The S&P 500 is moving sharply lower today"),
            ("a@example.com", "Apple is moving sharply lower today"),
        ]
        for n in rows:  # never a Tiingo price or percentage
            assert not re.search(r"\d+(\.\d+)?\s*%|\$", n.title + n.body)


def test_stale_or_old_session_quotes_raise_no_alerts(client):
    with services.session_scope() as s:
        accounts.ensure_user(s, "a@example.com")
        accounts.set_watchlist(s, "a@example.com", ["AAPL"])
        old = NOW.replace(hour=9, minute=0)
        assert intraday_alerts.notify(s, {"AAPL": (-9.0, old, NOW.date())}, NOW) == 0
        assert intraday_alerts.notify(s, {"AAPL": (-9.0, NOW, NOW.date().replace(day=24))}, NOW) == 0


def test_job_skips_outside_market_hours(monkeypatch, capsys):
    monkeypatch.setattr(config, "TIINGO_API_KEY", "t")
    monkeypatch.setattr(intraday_alerts, "market_hours", lambda now: False)
    monkeypatch.setattr(tiingo, "intraday_changes", lambda t: pytest.fail("no snapshot outside hours"))
    intraday_alerts.main()
    assert "market closed" in capsys.readouterr().out


def test_movers_page_and_portfolio_chips(client, snapshot):
    snapshot += [_row("AAPL", 93.0, 100.0), _row("MSFT", 101.0, 100.0), _row("SPY", 97.5, 100.0)]
    client.get("/demo")
    page = client.get("/movers").text
    assert "Movers" in page and "Moving sharply lower" in page and "Apple" in page
    assert "Microsoft" not in page.split("<h1>Movers</h1>")[1].split("Latest U.S. market close")[0]
    assert "Data sourced by Tiingo" in page and "embed-widget-single-quote" in page  # numbers from TradingView
    assert not re.search(r"7\.0\d*\s*%|>\s*93(\.0)?\s*<", page)  # no Tiingo figures
    portfolio = client.get("/portfolio").text
    assert "Moving sharply lower today" in portfolio and 'href="/movers"' in portfolio


def test_followed_stocks_use_the_viewers_threshold(client, snapshot):
    snapshot += [_row("AAPL", 100.0, 100.0), _row("MSFT", 96.5, 100.0)]
    sign_in(client, "c@example.com")
    services.save_watchlist("c@example.com", ["MSFT"])
    with services.session_scope() as s:
        accounts.set_prefs(s, "c@example.com", alert_threshold_pct=3.0)
    page = client.get("/movers").text
    assert "Microsoft" in page and "You follow" in page
    client.get("/logout")
    client.get("/demo")
    assert "Microsoft" not in client.get("/movers").text.split("<h1>Movers</h1>")[1]


def test_moves_outside_the_regular_session_are_labelled():
    tz = tiingo.NEW_YORK
    assert services.session_phase(datetime(2026, 11, 25, 9, 17, tzinfo=tz)) == "before the open"
    assert services.session_phase(datetime(2026, 11, 25, 12, 0, tzinfo=tz)) == "today"
    assert services.session_phase(datetime(2026, 11, 25, 17, 0, tzinfo=tz)) == "after the close"
    stock = services.Stock("AAPL", "Apple", "Tech", 1, "NASDAQ:AAPL")
    assert services.Mover(stock, "fell", False, "before the open").label == "Moving sharply lower before the open"
