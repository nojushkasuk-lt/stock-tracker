"""The FastAPI website: start page, demo (read-only), sign-in, portfolio, stock page, settings."""

from contextlib import contextmanager
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tracker import config, services
from tracker.db import create_tables, make_engine
from tracker.models import AiOutput, DailyReturn, Universe

D0 = date(2026, 1, 2)


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'web.db'}")
    create_tables(engine)
    with Session(engine) as s:
        for i, (t, n) in enumerate([("AAPL", "Apple"), ("MSFT", "Microsoft"), ("ZZZ", "Small Co")]):
            s.add(Universe(ticker=t, cik=str(i + 1), name=n, industry="Software", market_cap_rank=i + 1,
                           is_demo=t != "ZZZ", active=True, updated_at=datetime(2026, 1, 1)))
        s.flush()
        for k in range(300):
            d = D0 + timedelta(days=k)
            for t, r in (("AAPL", 0.5 if k % 2 else -0.3), ("SPY", 0.2 if k % 2 else -0.1)):
                s.add(DailyReturn(ticker=t, date=d, return_pct=r))
        s.add(AiOutput(kind="profile", scope_key="AAPL", model="m", input_hash="h", created_at=datetime(2026, 11, 1),
                       sources=[{"id": "K1", "url": "https://www.sec.gov/a.htm", "outlet": "SEC EDGAR"}, {"id": "M1", "url": None, "outlet": None}],
                       content={"overview": [{"text": "Apple <b>makes</b> phones.", "source_ids": ["K1"]}],
                                "strategy_and_trajectory": [{"text": "It invests in AI.", "source_ids": ["K1"]}],
                                "bull_case": [{"text": "Margins are 33.0%.", "source_ids": ["M1"]}],
                                "bear_case": [{"text": "Memory costs rise.", "source_ids": ["K1"]}], "what_changed": "Sales rose."}))
        s.commit()

    @contextmanager
    def scope():
        with Session(engine) as s:
            yield s
            s.commit()

    monkeypatch.setattr(services, "session_scope", scope)
    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "")      # local dev sign-in instead of Google
    monkeypatch.setattr(config, "BRAVE_SEARCH_API_KEY", "")
    from web.main import app
    return TestClient(app)


def sign_in(c, email="a@example.com"):
    return c.post("/dev-login", data={"email": email}, follow_redirects=False)


def test_start_page_offers_sign_in_and_demo_and_credits_the_owner(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Explore the demo" in r.text and "Sign in locally" in r.text
    assert config.OWNER_CREDIT in r.text and "Not investment advice" in r.text


def test_pages_need_sign_in_or_demo(client):
    for path in ("/portfolio", "/stock/AAPL", "/market"):
        assert client.get(path, follow_redirects=False).headers["location"] == "/"


def test_demo_is_read_only(client):
    client.get("/demo")
    r = client.get("/portfolio")
    assert "Demo · read-only" in r.text and "Apple" in r.text and "Small Co" not in r.text
    page = client.get("/stock/AAPL").text
    assert "Refresh now" not in page and "Find recent coverage" not in page and "Write a note now" not in page
    assert client.get("/stock/ZZZ").status_code == 404           # not a demo stock
    assert client.post("/stock/AAPL/refresh").status_code == 403
    assert client.get("/settings", follow_redirects=False).status_code == 303
    assert "Brave Search API" in page and "TradingView" in page and config.OWNER_CREDIT in page


def test_stock_page_shows_performance_profile_sources_and_escapes_model_text(client):
    client.get("/demo")
    page = client.get("/stock/AAPL").text
    for label in ("1D", "1W", "1M", "6M", "1Y"):
        assert f'data-range="{label}"' in page
    assert 'data-range="5Y"' not in page                        # only 300 days of history
    assert "Apple &lt;b&gt;makes&lt;/b&gt; phones." in page      # autoescaped, never raw HTML
    assert "Strategy &amp; outlook" in page and "What changed" in page
    assert "Sources &amp; further reading" in page and "our figures from SEC filings" in page
    assert "Beta vs S&amp;P 500" in page and "Volatility" in page


def test_sign_in_pick_stocks_and_outlets(client):
    assert sign_in(client).headers["location"] == "/portfolio"
    assert "Pick up to 15 stocks" in client.get("/portfolio").text
    r = client.post("/settings", data={"ticker": ["AAPL", "ZZZ"], "outlet": ["reuters.com"]}, follow_redirects=False)
    assert r.status_code == 303
    p = client.get("/portfolio").text
    assert "Small Co" in p and "2 of 15" in p
    s = client.get("/settings").text
    assert 'value="ZZZ" checked' in s and 'value="reuters.com" checked' in s
    assert "Refresh now" in client.get("/stock/AAPL").text or "Write a note now" in client.get("/stock/AAPL").text


def test_settings_rejects_more_than_15(client, monkeypatch):
    monkeypatch.setattr(config, "WATCHLIST_MAX", 1)
    sign_in(client)
    r = client.post("/settings", data={"ticker": ["AAPL", "MSFT"]})
    assert r.status_code == 200 and "at most 1" in r.text


def test_dev_login_is_off_when_google_is_configured_or_in_prod(client, monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "x")
    monkeypatch.setattr(config, "GOOGLE_CLIENT_SECRET", "y")
    sign_in(client)
    assert client.get("/portfolio", follow_redirects=False).status_code == 303
    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "")
    monkeypatch.setattr(config, "APP_ENV", "prod")
    sign_in(client)
    assert client.get("/portfolio", follow_redirects=False).status_code == 303


def test_unknown_stock_is_404(client):
    sign_in(client)
    assert client.get("/stock/NOPE").status_code == 404
