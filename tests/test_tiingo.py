"""Tiingo snapshot parsing and the watchlist aggregate (transient, in memory)."""

from datetime import date

import pytest

from tracker import config
from tracker.data.providers import tiingo


def _row(ticker, last, prev, ts="2026-11-25T10:30:00-05:00", prev_date="2026-11-24"):
    return {"ticker": ticker, "tngoLast": last, "prevClose": prev, "timestamp": ts, "prevDate": prev_date}


@pytest.fixture
def snapshot(monkeypatch):
    rows = []

    def fake_fetch(token):
        return {r["ticker"].upper(): m for r in rows if (m := tiingo._parse_move(r))}

    monkeypatch.setattr(config, "TIINGO_API_KEY", "test-token")
    monkeypatch.setattr(tiingo, "_fetch", fake_fetch)
    monkeypatch.setattr(tiingo, "_refresh_at", 0.0)
    return rows


def test_share_classes_match_tiingo_dash_symbols(snapshot):
    snapshot += [_row("BRK-B", 99.0, 100.0), _row("AAPL", 103.0, 100.0)]
    change = tiingo.watchlist_change(["BRK-B", "AAPL"])
    assert change is not None and change.covered == 2
    assert change.percent == pytest.approx(1.0)
    assert tiingo.watchlist_change(["BRK.B", "AAPL"]).covered == 2  # dotted input is normalised too


def test_aggregate_uses_only_the_latest_comparable_session(snapshot):
    snapshot += [_row("AAPL", 110.0, 100.0), _row("MSFT", 90.0, 100.0),
                 _row("OLD", 200.0, 100.0, ts="2026-11-20T15:00:00-05:00", prev_date="2026-11-19")]
    change = tiingo.watchlist_change(["AAPL", "MSFT", "OLD"])
    assert change.covered == 2 and change.percent == pytest.approx(0.0)


def test_single_stock_or_unconfigured_feed_gives_no_aggregate(snapshot, monkeypatch):
    snapshot += [_row("AAPL", 110.0, 100.0)]
    assert tiingo.watchlist_change(["AAPL"]) is None
    monkeypatch.setattr(config, "TIINGO_API_KEY", "")
    assert tiingo.watchlist_change(["AAPL", "MSFT"]) is None


def test_overnight_trading_counts_toward_the_next_session():
    # 8 p.m. Eastern rolls the baseline: an overnight print belongs to the next day's session.
    move = tiingo._parse_move(_row("NVDA", 147.44, 155.38, ts="2026-11-24T21:30:00-05:00"))
    assert move.session == date(2026, 11, 25) and move.previous_session == date(2026, 11, 24)
    assert tiingo._parse_move(_row("NVDA", 1.0, 0.0)) is None  # no division by a zero close


def test_notable_move_exposes_direction_and_session_only(snapshot):
    snapshot += [_row("NVDA", 94.0, 100.0)]
    move = tiingo.notable_move("NVDA")
    assert move == tiingo.NotableMove("fell", date(2026, 11, 25), date(2026, 11, 24))
    snapshot[:] = [_row("NVDA", 99.0, 100.0)]
    tiingo._refresh_at = 0.0
    assert tiingo.notable_move("NVDA") is None
