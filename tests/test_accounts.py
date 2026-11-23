"""Users, watchlists, outlets and the caps (AGENTS.md rule 6)."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker import accounts, config
from tracker.db import create_tables, make_engine
from tracker.models import RefreshRequest, Universe, User

NOW = datetime(2026, 11, 23, 15, 0)
E = "a@example.com"


@pytest.fixture
def db(tmp_path):
    e = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    create_tables(e)
    with Session(e) as s:
        for i in range(20):
            s.add(Universe(ticker=f"T{i:02d}", cik="1", name=f"Co {i}", industry="X", active=(i != 19), updated_at=NOW))
        s.flush()
        accounts.ensure_user(s, E, NOW)
        accounts.ensure_user(s, "b@example.com", NOW)
        yield s


def test_ensure_user_normalizes_and_updates_last_login(db):
    u = accounts.ensure_user(db, "  A@Example.com ", NOW + timedelta(days=1))
    assert u.email == E and u.created_at == NOW and u.last_login == NOW + timedelta(days=1)
    assert len(db.scalars(select(User)).all()) == 2


def test_watchlist_up_to_15_stocks(db):
    assert accounts.set_watchlist(db, E, [f"T{i:02d}" for i in range(15)], NOW)[:2] == ["T00", "T01"]
    with pytest.raises(accounts.WatchlistError, match="at most 15"):
        accounts.set_watchlist(db, E, [f"T{i:02d}" for i in range(16)], NOW)
    assert len(accounts.watchlist(db, E)) == 15


def test_watchlist_rejects_unknown_tickers_and_dedupes(db):
    assert accounts.set_watchlist(db, E, ["t01", "T01", " T02 "], NOW) == ["T01", "T02"]
    with pytest.raises(accounts.WatchlistError, match="ZZZ"):
        accounts.set_watchlist(db, E, ["T01", "ZZZ"], NOW)


def test_stock_that_left_the_top_100_stays_for_followers_but_cannot_be_added(db):
    db.get(Universe, "T19").active = True
    accounts.set_watchlist(db, E, ["T19"], NOW)
    db.get(Universe, "T19").active = False
    assert set(accounts.set_watchlist(db, E, ["T19", "T01"], NOW)) == {"T19", "T01"}  # kept
    with pytest.raises(accounts.WatchlistError, match="top 100"):
        accounts.set_watchlist(db, "b@example.com", ["T19"], NOW)


def test_outlets_must_be_configured(db):
    assert accounts.set_outlets(db, E, ["reuters.com", "cnbc.com"]) == {"reuters.com", "cnbc.com"}
    with pytest.raises(ValueError):
        accounts.set_outlets(db, E, ["evil.example"])
    assert accounts.set_outlets(db, E, []) == set()  # empty = all outlets


def refresh(db, ticker, now, ok=True, email=E):
    return accounts.request_refresh(db, email, ticker, lambda: ok, now)


def test_fourth_refresh_in_a_day_is_refused(db):
    for i, t in enumerate(["T01", "T02", "T03"]):
        assert refresh(db, t, NOW + timedelta(minutes=i)).status == "done"
    out = refresh(db, "T04", NOW + timedelta(minutes=5))
    assert out.status == "refused_cap" and "3 refreshes" in out.message
    assert accounts.refreshes_left_today(db, E, NOW) == 0
    assert refresh(db, "T04", NOW + timedelta(days=1)).status == "done"  # new UTC day


def test_a_refresh_is_shared_with_everyone_for_six_hours(db):
    called = []
    accounts.request_refresh(db, E, "T01", lambda: called.append(1) or True, NOW)
    out = accounts.request_refresh(db, "b@example.com", "T01", lambda: called.append(2) or True, NOW + timedelta(hours=5))
    assert out.status == "served_from_cache" and called == [1]
    assert accounts.refreshes_left_today(db, "b@example.com", NOW) == 3  # shared refreshes are free
    assert refresh(db, "T01", NOW + timedelta(hours=6, minutes=1), email="b@example.com").status == "done"


def test_failed_refresh_does_not_use_the_cap(db):
    assert refresh(db, "T01", NOW, ok=False).status == "failed"
    assert accounts.refreshes_left_today(db, E, NOW) == 3


def test_exceptions_in_the_refresh_count_as_failed(db):
    def boom():
        raise RuntimeError("search down")
    assert accounts.request_refresh(db, E, "T01", boom, NOW).status == "failed"


def test_monthly_total_cap(db, monkeypatch):
    monkeypatch.setattr(config, "REFRESH_PER_MONTH", 2)
    assert refresh(db, "T01", NOW).status == "done"
    assert refresh(db, "T02", NOW, email="b@example.com").status == "done"
    out = refresh(db, "T03", NOW)
    assert out.status == "refused_cap" and "this month" in out.message


def test_ten_coverage_searches_per_user_per_day(db):
    assert all(accounts.use_coverage_search(db, E, "T01", NOW) for _ in range(10))
    assert accounts.use_coverage_search(db, E, "T01", NOW) is False
    assert accounts.use_coverage_search(db, "b@example.com", "T01", NOW) is True
    assert accounts.coverage_searches_left_today(db, E, NOW + timedelta(days=1)) == 10
    refused = db.scalars(select(RefreshRequest).where(RefreshRequest.status == "refused_cap")).all()
    assert len(refused) == 1
