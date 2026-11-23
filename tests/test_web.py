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


def _range(label, pct):
    return services.ChartRange(label, pct, label.lower(), "0,240 1000,10", [["Jan 2", 100.0], ["Nov 20", 110.0]], 100.0, 110.0)


FAKE_CHART = services.PriceChart(110.0, [_range(x, v) for x, v in
                                         [("1D", -1.9), ("1W", -3.5), ("1M", -1.6), ("6M", 11.1), ("1Y", 28.0), ("5Y", 134.0), ("MAX", 349280.3)]])


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
    monkeypatch.setattr(services, "get_price_chart", lambda t: FAKE_CHART if t.upper() == "AAPL" else None)
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
    for label in ("1D", "1W", "1M", "6M", "1Y", "5Y", "MAX"):
        assert f'data-range="{label}"' in page
    assert "+349,280.3%" in page
    assert page.count('data-perf>') == 1 and "advanced-chart" not in page   # one chart, not two
    assert "symbol-info" not in page                             # valuation is ours, not a widget
    assert "Apple &lt;b&gt;makes&lt;/b&gt; phones." in page      # autoescaped, never raw HTML
    assert "Strategy &amp; outlook" in page and "What changed" in page
    assert "Sources &amp; further reading" in page and "our figures from SEC filings" in page
    assert "Beta vs S&amp;P 500" in page and "Volatility" in page


def test_sign_in_pick_stocks_and_outlets(client):
    assert sign_in(client).headers["location"] == "/welcome"  # first sign-in: setup steps
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


def test_without_local_chart_data_the_page_shows_only_the_tradingview_chart(client):
    client.get("/demo")
    page = client.get("/stock/MSFT").text
    assert "advanced-chart" in page and "data-perf>" not in page and '"backgroundColor": "#121E33"' in page


def test_demo_visitors_can_get_to_sign_in(client):
    client.get("/demo")
    r = client.get("/")
    assert r.status_code == 200 and "Sign in locally" in r.text and "Back to the demo" in r.text
    assert sign_in(client).headers["location"] == "/welcome"
    assert "Demo · read-only" not in client.get("/portfolio").text


def test_logos_and_key_facts_from_wikidata(client, monkeypatch):
    facts = services.KeyFacts("John Ternus", "2026-09-01", "Cupertino", "United States", 1976, 164000,
                              "https://www.apple.com/", "https://en.wikipedia.org/wiki/Apple_Inc.", "https://www.wikidata.org/wiki/Q312", "2026-11-23")
    monkeypatch.setattr(services, "get_key_facts", lambda t: facts)
    real = services.get_stock
    monkeypatch.setattr(services, "get_stock", lambda t: real(t) and services.Stock(**{**real(t).__dict__, "logo": "https://commons.wikimedia.org/wiki/Special:FilePath/A.svg?width=128"}))
    client.get("/demo")
    page = client.get("/stock/AAPL").text
    assert "John Ternus · since Sep 2026" in page and "164,000" in page and "apple.com" in page
    assert 'src="https://commons.wikimedia.org/wiki/Special:FilePath/A.svg?width=128"' in page
    assert "Key facts · Wikidata" in page and "Logo · Wikimedia Commons" in page


def test_valuation_from_latest_close_and_filings():
    from web.views import valuation
    m = type("M", (), {"eps_diluted_ttm": 8.0, "net_income_ttm": 80e9, "revenue_ttm": 400e9, "net_debt": 20e9, "ebitda_ttm": 120e9})()
    v = dict((label, value) for label, value, _ in valuation(m, 200.0)["metrics"])
    assert v["Market value"] == "$2.0T" and v["P/E"] == "25.0x" and v["Price / sales"] == "5.0x" and v["EV / EBITDA"] == "16.8x"
    assert valuation(m, None) is None



def test_setup_needs_three_stocks_then_markets_news_alerts(client):
    sign_in(client)
    r = client.post("/welcome", data={"step": "stocks", "ticker": ["AAPL", "MSFT"]})
    assert r.status_code == 200 and "at least 3" in r.text
    r = client.post("/welcome", data={"step": "stocks", "ticker": ["AAPL", "MSFT", "ZZZ"]}, follow_redirects=False)
    assert r.headers["location"] == "/welcome?step=markets"
    assert client.post("/welcome", data={"step": "markets", "market": ["VOO", "GLD"]}, follow_redirects=False).headers["location"] == "/welcome?step=news"
    assert client.post("/welcome", data={"step": "news", "skip": "1"}, follow_redirects=False).headers["location"] == "/welcome?step=alerts"
    r = client.post("/welcome", data={"step": "alerts", "stock_alerts": "1", "alert_threshold_pct": "3.0", "digest": "off"}, follow_redirects=False)
    assert r.headers["location"] == "/portfolio"
    assert services.get_prefs("a@example.com").alert_threshold_pct == 3.0 and not services.get_prefs("a@example.com").market_alerts
    assert services.get_followed_market_tickers("a@example.com") == ["GLD", "VOO"] or set(services.get_followed_market_tickers("a@example.com")) == {"GLD", "VOO"}
    client.get("/logout")
    assert sign_in(client).headers["location"] == "/portfolio"  # setup done: straight to the start page


def test_settings_sections_and_prefs_save(client):
    sign_in(client)
    s = client.get("/settings").text
    for section in ('id="stocks"', 'id="markets"', 'id="news"', 'id="alerts"', 'id="display"', 'id="account"'):
        assert section in s
    r = client.post("/settings", data={"ticker": ["AAPL"], "start_AAPL": "2025-01-02", "market": ["QQQ"], "outlet": [],
                                       "alert_threshold_pct": "7.5", "digest": "daily", "home": "news", "perf_basis": "1Y"},
                    follow_redirects=False)
    assert r.status_code == 303
    p = services.get_prefs("a@example.com")
    assert (p.alert_threshold_pct, p.digest, p.home, p.stock_alerts) == (7.5, "daily", "news", False)
    assert services.get_start_dates("a@example.com") == {"AAPL": "2025-01-02"}
    assert 'value="2025-01-02"' in client.get("/settings").text


def test_markets_page_and_fund_page(client):
    client.get("/demo")
    m = client.get("/market").text
    for g in ("US indexes", "International", "Bonds", "Commodities", "Sectors"):
        assert g in m
    assert "/etf/VOO" in m
    f = client.get("/etf/VOO")
    assert f.status_code == 200 and "Vanguard" in f.text
    assert client.get("/etf/NOPE").status_code == 404


def test_alerts_page_and_bell(client):
    from tracker import accounts
    sign_in(client)
    with services.session_scope() as s:  # the test database the app uses
        accounts.notify(s, "a@example.com", kind="stock", ticker="AAPL", title="AAPL fell 6.0%", body="Coverage points to ...",
                        url="/stock/AAPL", dedupe_key="move:AAPL:x")
    assert "1 unread" in client.get("/portfolio").text
    assert "AAPL fell 6.0%" in client.get("/alerts").text
    assert "unread" not in client.get("/portfolio").text.split("Alerts", 1)[1][:30]


def test_news_page_shows_without_searching(client):
    client.get("/demo")
    r = client.get("/news")
    assert r.status_code == 200 and "Market today" in r.text and "Load latest" not in r.text


def test_link_mode_closes_the_site_except_for_shared_links(client, monkeypatch):
    monkeypatch.setattr(config, "ACCESS_MODE", "link")
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 403 and "This site is private" in r.text and r.headers["X-Robots-Tag"].startswith("noindex")
    assert client.get("/demo", follow_redirects=False).status_code == 403
    assert client.get("/s/made-up").status_code == 403
    token = services.create_share_link("Recruiter")
    assert client.get(f"/s/{token}", follow_redirects=False).headers["location"] == "/"
    assert client.get("/demo").status_code == 200
    services.revoke_share_link(token)
    assert client.get("/market", follow_redirects=False).status_code == 403  # revoked: access ends at once


def test_link_mode_lets_known_users_sign_in_and_refuses_strangers(client, monkeypatch):
    monkeypatch.setattr(config, "ACCESS_MODE", "link")
    monkeypatch.setattr(config, "OWNER_EMAIL", "owner@example.com")
    assert sign_in(client, "stranger@example.com").headers["location"] == "/"
    assert not services.known_user("stranger@example.com")
    assert sign_in(client, "owner@example.com").headers["location"] == "/welcome"


def test_shared_links_admin_is_owner_only(client, monkeypatch):
    monkeypatch.setattr(config, "OWNER_EMAIL", "owner@example.com")
    sign_in(client)
    assert client.get("/admin/links").status_code == 404
    client.get("/logout")
    sign_in(client, "owner@example.com")
    r = client.post("/admin/links", data={"label": "Acme"})
    assert r.status_code == 200 and "/s/" in r.text and "Acme" in r.text
