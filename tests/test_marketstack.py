"""Marketstack EOD provider: percent changes only, request sizing, key never in errors, incremental plan."""

from datetime import date, timedelta

import httpx
import pytest

from tracker.data import prices
from tracker.data.providers.marketstack import Marketstack, MarketstackError

KEY = "secret-key-123"


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _rows(symbol, closes, first=date(2026, 11, 16)):
    return [{"symbol": symbol, "date": f"{first + timedelta(days=i)}T00:00:00+0000", "close": c * 2, "adj_close": c}
            for i, c in enumerate(closes)]


def test_daily_returns_are_percent_changes_of_adjusted_closes():
    seen = []

    def handler(request):
        seen.append(request.url.params)
        data = _rows("AAPL", [100, 110, 99]) + _rows("BRK-B", [50, 50])
        return httpx.Response(200, json={"pagination": {"total": len(data)}, "data": data})

    ms = Marketstack(KEY, _client(handler), pause=0)
    out = ms.daily_returns(["AAPL", "BRK-B"], date(2026, 11, 17), date(2026, 11, 20))
    assert out["AAPL"] == [(date(2026, 11, 17), pytest.approx(10.0)), (date(2026, 11, 18), pytest.approx(-10.0))]
    assert out["BRK-B"] == [(date(2026, 11, 17), 0.0)]
    assert seen[0]["symbols"] == "AAPL,BRK-B" and seen[0]["date_from"] == "2026-11-10"
    assert ms.requests == 2  # billed per symbol


def test_long_ranges_fetch_one_symbol_per_request_and_follow_pages():
    calls = []

    def handler(request):
        p = request.url.params
        calls.append((p["symbols"], int(p["offset"])))
        rows = _rows(p["symbols"], [100.0 + i for i in range(3)], first=date(2021, 1, 4) + timedelta(days=int(p["offset"])))
        return httpx.Response(200, json={"pagination": {"total": 6}, "data": rows})

    ms = Marketstack(KEY, _client(handler), pause=0)
    out = ms.closes(["SPY", "QQQ"], date(2021, 1, 1), date(2026, 1, 1))
    assert calls == [("SPY", 0), ("SPY", 3), ("QQQ", 0), ("QQQ", 3)]
    assert len(out["SPY"]) == 6


def test_errors_never_contain_the_access_key():
    def handler(request):
        return httpx.Response(401, json={"error": {"code": "unauthorized", "message": "verify your access key"}})

    with pytest.raises(MarketstackError) as exc:
        Marketstack(KEY, _client(handler), pause=0).daily_returns(["AAPL"], date(2026, 11, 17))
    assert KEY not in str(exc.value) and "unauthorized" in str(exc.value)

    def broken(request):
        raise httpx.ConnectError(f"cannot reach {request.url}")

    with pytest.raises(MarketstackError) as exc:
        Marketstack(KEY, _client(broken), pause=0).daily_returns(["AAPL"], date(2026, 11, 17))
    assert KEY not in str(exc.value)


def test_monthly_quota_stops_instead_of_retrying():
    def handler(request):
        return httpx.Response(429, json={"error": {"code": "too_many_requests", "message": "Monthly request quota exceeded"}})

    with pytest.raises(MarketstackError, match="quota"):
        Marketstack(KEY, _client(handler), pause=0).daily_returns(["AAPL"], date(2026, 11, 17))


def test_missing_key_refuses_to_start(monkeypatch):
    monkeypatch.setattr("tracker.config.MARKETSTACK_API_KEY", "")
    with pytest.raises(MarketstackError):
        Marketstack()
    monkeypatch.setattr("tracker.config.MARKETSTACK_API_KEY", KEY)
    assert isinstance(prices.get_provider("marketstack"), Marketstack)


def test_fetch_plan_only_backfills_new_or_stale_tickers():
    today = date(2026, 11, 25)
    last = {"AAPL": date(2026, 11, 20), "MSFT": date(2026, 11, 24), "OLD": date(2026, 6, 1)}
    plan = prices.fetch_plan(last, ["AAPL", "MSFT", "OLD", "NEW"], today)
    assert plan[0] == (["AAPL", "MSFT"], date(2026, 11, 20))
    assert plan[1][0] == ["OLD", "NEW"] and plan[1][1].year == 2021
