from datetime import datetime

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker import config
from tracker.data import news
from tracker.db import create_tables, make_engine
from tracker.models import UsageLog

PAYLOAD = {"results": [
    {"title": "Apple beats estimates", "url": "https://www.reuters.com/tech/apple-1", "page_age": "2026-11-20T21:00:00", "description": "full text we must not show"},
    {"title": "Apple shares slip", "url": "https://www.wsj.com/a/apple-2", "page_age": "2026-11-21T09:30:00Z"},
    {"title": "Apple blog post", "url": "https://randomblog.example/apple", "page_age": "2026-11-21T10:00:00"},
    {"title": "Dupe", "url": "https://www.reuters.com/tech/apple-1", "page_age": "2026-11-20T21:00:00"},
    {"title": "Yahoo story", "url": "https://finance.yahoo.com/news/apple-3", "page_age": None},
    {"title": "Yahoo mail is not finance", "url": "https://mail.yahoo.com/x"},
    {"url": "https://www.cnbc.com/no-title"},
]}


@pytest.fixture
def db(tmp_path):
    e = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    create_tables(e)
    with Session(e) as s:
        yield s


@pytest.fixture(autouse=True)
def _clear():
    news.clear_cache()


class FakeBrave:
    def __init__(self, payload=PAYLOAD):
        self.calls, self.payload = 0, payload

    def search(self, q, freshness="pw"):
        self.calls += 1
        return news.parse_results(self.payload)


def test_outlets_file_loads():
    outlets = news.load_outlets()
    assert {o.domain for o in outlets} >= {"reuters.com", "wsj.com", "bloomberg.com"}
    assert next(o for o in outlets if o.domain == "wsj.com").paywall


def test_match_outlet_handles_subdomains_and_rejects_lookalikes():
    outlets = news.load_outlets()
    assert news.match_outlet("https://www.reuters.com/x", outlets).name == "Reuters"
    assert news.match_outlet("https://finance.yahoo.com/x", outlets).name == "Yahoo Finance"
    assert news.match_outlet("https://mail.yahoo.com/x", outlets) is None
    assert news.match_outlet("https://notreuters.com/x", outlets) is None
    assert news.match_outlet("https://reuters.com.evil.example/x", outlets) is None


def test_parse_drops_article_text_and_incomplete_results():
    rows = news.parse_results(PAYLOAD)
    assert all(set(r) == {"title", "url", "published"} for r in rows)
    assert len(rows) == 6  # the one without a title is dropped


def test_coverage_links_filters_to_chosen_outlets_dedupes_and_sorts_newest_first():
    links = news.coverage_links(news.parse_results(PAYLOAD), news.load_outlets())
    assert [l.outlet for l in links] == ["The Wall Street Journal", "Reuters", "Yahoo Finance"]
    assert links[0].paywall and not links[1].paywall
    only_wsj = news.coverage_links(news.parse_results(PAYLOAD), news.load_outlets(), domains={"wsj.com"})
    assert [l.domain for l in only_wsj] == ["wsj.com"]


def test_cache_shares_results_and_only_real_calls_count(db):
    brave, clock = FakeBrave(), iter([0, 10, 4000]).__next__
    news.cached_search(db, brave, "q", now=clock)
    news.cached_search(db, brave, "q", now=clock)
    assert brave.calls == 1 and news.searches_this_month(db) == 1
    news.cached_search(db, brave, "q", now=clock)  # expired
    assert brave.calls == 2 and news.searches_this_month(db) == 2


def test_cache_never_outlives_one_hour(monkeypatch, db):
    monkeypatch.setattr(config, "NEWS_CACHE_SECONDS", 99999)  # misconfigured
    brave, clock = FakeBrave(), iter([0, 3600]).__next__
    news.cached_search(db, brave, "q", now=clock)
    news.cached_search(db, brave, "q", now=clock)
    assert brave.calls == 2


def test_monthly_cap_stops_searches(monkeypatch, db):
    monkeypatch.setattr(config, "MONTHLY_SEARCH_CAP", 2)
    brave = FakeBrave()
    news.cached_search(db, brave, "a")
    news.cached_search(db, brave, "b")
    with pytest.raises(news.SearchCapReached):
        news.cached_search(db, brave, "c")
    assert brave.calls == 2
    news.cached_search(db, brave, "a")  # still served from cache after the cap


def test_cap_counts_only_this_month(db):
    db.add(UsageLog(created_at=datetime(2026, 10, 31, 23, 59), job="coverage", search_calls=500, cost_usd=0))
    db.flush()
    assert news.searches_this_month(db, now=datetime(2026, 11, 2)) == 0


def test_brave_client_sends_key_and_needs_one():
    with pytest.raises(news.NewsNotConfigured):
        news.BraveNews(api_key="")
    seen = {}

    def handler(req):
        seen["key"], seen["q"] = req.headers["x-subscription-token"], req.url.params["q"]
        return httpx.Response(200, json=PAYLOAD)

    b = news.BraveNews(api_key="k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert len(b.search('"Apple" AAPL stock')) == 6 and seen == {"key": "k", "q": '"Apple" AAPL stock'}


def test_nothing_about_news_is_stored_in_the_database(db):
    news.cached_search(db, FakeBrave(), "q")
    from tracker.models import Base
    assert "articles" not in Base.metadata.tables  # results only live in memory
    assert db.scalar(select(UsageLog.search_calls)) == 1
