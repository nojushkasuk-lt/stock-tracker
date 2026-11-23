"""explain_day: the ladder decides the searches; one market note on a sell-off; rechecks; market-note interval."""

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from test_llm import fake
from tracker import config
from tracker.ai import notes
from tracker.ai.citations import Claim
from tracker.ai.notes import MoveNoteOut
from tracker.analysis import moves
from tracker.data import news
from tracker.db import create_tables, make_engine
from tracker.models import AiOutput, DailyReturn, Filing, Move, Universe, UsageLog

D = date(2026, 11, 20)
NOW = datetime(2026, 11, 20, 22, 0)
EXPLAINED = MoveNoteOut(summary="Coverage around the move points to an AI sell-off.", confidence="medium",
                        claims=[Claim(text="Reports suggest an AI sell-off weighed on shares.", source_ids=["N1"])],
                        ranked_source_ids=["N1"])
NOTHING = MoveNoteOut(summary="No clear catalyst found yet.", confidence="low")


class FakeBrave:
    def __init__(self, tag="a"):
        self.queries, self.tag = [], tag

    def search(self, q, freshness="pw", count=50):
        self.queries.append((q, freshness))
        n = f"{self.tag}{len(self.queries)}"
        return [{"title": f"Story {n}", "url": f"https://www.reuters.com/s{n}",
                 "published": datetime(2026, 11, 20, 15)}]


class FakeFetcher:
    def __init__(self):
        self.urls = []

    def sections(self, form, items, url):
        from tracker.data.filing_text import Section
        self.urls.append(url)
        return [Section("earnings_release", "8-K item 2.02 earnings release", "Revenue was $10.0 billion.", url)]


@pytest.fixture(autouse=True)
def _clear():
    news.clear_cache()


@pytest.fixture
def db(tmp_path):
    e = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    create_tables(e)
    with Session(e) as s:
        yield s


def setup_day(db, returns, spy, industries=None):
    db.add(DailyReturn(ticker="SPY", date=D, return_pct=spy))
    for t, r in returns.items():
        db.add(Universe(ticker=t, cik="1", name=f"{t} Inc", industry=(industries or {}).get(t, f"Ind-{t}"),
                        is_demo=True, updated_at=NOW))
        db.add(DailyReturn(ticker=t, date=D, return_pct=r))
    db.flush()
    d = moves.load_day(db, D, covered=set(returns))
    moves.record_day(db, d)
    return d


def run(db, d, client, brave=None, fetcher=None, now=NOW, **kw):
    return notes.explain_day(db, d, brave or FakeBrave(), fetcher or FakeFetcher(), client=client, now=now, **kw)


def statuses(db):
    return {m.ticker: m.status for m in db.scalars(select(Move))}


def test_single_stock_move_gets_its_own_note_and_search(db):
    d = setup_day(db, {"UNH": -6.0, "AAA": 0.1, "BBB": -0.2}, -0.3)
    brave = FakeBrave()
    rep = run(db, d, fake(parsed=EXPLAINED), brave)
    assert rep.notes == {"UNH": "written"} and len(brave.queries) == 1
    assert brave.queries[0][1] == "2026-11-19to2026-11-20"  # window ends on the move date
    m = db.scalars(select(Move).where(Move.ticker == "UNH")).one()
    note = db.get(AiOutput, m.note_id)
    assert (m.status, note.kind, note.scope_key) == ("explained", "stock_note", "UNH")
    assert note.content["date"] == "2026-11-20" and note.content["return_pct"] == -6.0


def test_forty_stocks_falling_together_get_one_market_note_and_one_search(db):
    returns = {f"S{i:02d}": -5.0 - (i % 5) * 0.3 for i in range(40)}
    d = setup_day(db, returns, -4.4, industries={t: f"Ind{i % 8}" for i, t in enumerate(returns)})
    brave, c = FakeBrave(), fake(parsed=EXPLAINED)
    rep = run(db, d, c, brave)
    assert rep.notes == {"market": "written"}
    assert len(brave.queries) == 1 and "S&P 500" in brave.queries[0][0]
    assert len(c.messages.parse_calls) == 1
    note_ids = {m.note_id for m in db.scalars(select(Move))}
    assert len(note_ids) == 1 and db.get(AiOutput, note_ids.pop()).kind == "market_note"
    assert set(statuses(db).values()) == {"explained"}


def test_industry_moves_share_one_note(db):
    ind = {"NVDA": "Semis", "AMD": "Semis", "MU": "Semis", "AVGO": "Semis"}
    d = setup_day(db, {"NVDA": -7.0, "AMD": -6.5, "MU": -6.0, "AVGO": -5.5}, -1.0, industries=ind)
    brave = FakeBrave()
    rep = run(db, d, fake(parsed=EXPLAINED), brave)
    assert rep.notes == {"industry:Semis": "written"} and len(brave.queries) == 1
    assert '"NVDA Inc" OR "AMD Inc" OR "MU Inc"' in brave.queries[0][0]  # biggest movers first
    assert len({m.note_id for m in db.scalars(select(Move))}) == 1


def test_market_alert_day_writes_the_market_note_even_without_stock_moves(db):
    d = setup_day(db, {"AAA": -2.5}, -2.4)
    rep = run(db, d, fake(parsed=EXPLAINED))
    assert rep.notes == {"market": "written"}


def test_market_note_is_refreshed_at_most_every_three_hours(db):
    d = setup_day(db, {"AAA": -2.5}, -2.4)
    run(db, d, fake(parsed=EXPLAINED))
    brave = FakeBrave()
    assert run(db, d, fake(parsed=EXPLAINED), brave, now=NOW + timedelta(hours=2)).notes == {"market": "reused"}
    assert brave.queries == []
    news.clear_cache()  # the in-memory news cache would also have expired by then
    later = run(db, d, fake(parsed=EXPLAINED), FakeBrave("b"), now=NOW + timedelta(hours=3, minutes=1))
    assert later.notes == {"market": "written"}
    assert len(db.scalars(select(AiOutput)).all()) == 2


def test_no_catalyst_is_rechecked_once_then_final(db):
    d = setup_day(db, {"UNH": -6.0}, -0.3)
    run(db, d, fake(parsed=NOTHING))
    m = db.scalars(select(Move)).one()
    assert m.status == "recheck" and m.recheck_after == NOW + timedelta(hours=config.RECHECK_AFTER_HOURS)
    assert run(db, d, fake(parsed=NOTHING), only_pending=True, now=NOW + timedelta(hours=1)).notes == {}  # too early
    news.clear_cache()
    run(db, d, fake(parsed=NOTHING), only_pending=True, now=NOW + timedelta(hours=9))
    assert m.status == "no_catalyst" and m.recheck_after is None


def test_recheck_that_finds_a_cause_explains_the_move(db):
    d = setup_day(db, {"UNH": -6.0}, -0.3)
    run(db, d, fake(parsed=NOTHING))
    news.clear_cache()
    run(db, d, fake(parsed=EXPLAINED), FakeBrave("later"), only_pending=True, now=NOW + timedelta(hours=9))
    assert statuses(db) == {"UNH": "explained"}


def test_earnings_release_is_used_only_when_filed_before_the_close(db):
    d = setup_day(db, {"TJX": 8.0}, -0.3)
    # 8:00 am ET before the open (13:00 UTC) and 4:37 pm ET after the close (21:37 UTC); Nov = EST (UTC-5)
    db.add(Filing(accession="pre", ticker="TJX", form="8-K", items="2.02,9.01", filed_at=datetime(2026, 11, 20, 13, 0), url="https://sec/pre.htm"))
    db.add(Filing(accession="post", ticker="TJX", form="8-K", items="2.02,9.01", filed_at=datetime(2026, 11, 20, 21, 37), url="https://sec/post.htm"))
    db.flush()
    fetcher, c = FakeFetcher(), fake(parsed=EXPLAINED)
    run(db, d, c, fetcher=fetcher)
    assert fetcher.urls == ["https://sec/pre.htm"]
    assert "[F1] kind=primary" in c.messages.parse_calls[0]["messages"][0]["content"]


def test_close_time_follows_daylight_saving():
    assert notes._close_utc(date(2026, 7, 15)) == datetime(2026, 7, 15, 20, 0)   # EDT
    assert notes._close_utc(date(2026, 11, 20)) == datetime(2026, 11, 20, 21, 0)  # EST


def test_budget_stop_leaves_moves_pending(db, monkeypatch):
    d = setup_day(db, {"UNH": -6.0}, -0.3)
    monkeypatch.setattr(config, "MONTHLY_BUDGET_USD", 0.0)
    rep = run(db, d, fake(parsed=EXPLAINED))
    assert rep.stopped.startswith("BudgetExceeded") and statuses(db) == {"UNH": "pending"}


def test_search_cap_stops_cleanly(db, monkeypatch):
    d = setup_day(db, {"UNH": -6.0}, -0.3)
    monkeypatch.setattr(config, "MONTHLY_SEARCH_CAP", 0)
    rep = run(db, d, fake(parsed=EXPLAINED))
    assert rep.stopped.startswith("SearchCapReached") and statuses(db) == {"UNH": "pending"}
    assert db.scalars(select(UsageLog)).first() is None


def test_refresh_writes_a_stock_note_for_the_latest_day_and_links_the_move(db):
    d = setup_day(db, {"UNH": -6.0, "AAA": 0.2}, -0.3)
    run(db, d, fake(parsed=NOTHING))
    news.clear_cache()
    note = notes.refresh_stock(db, "unh", FakeBrave("fresh"), FakeFetcher(), client=fake(parsed=EXPLAINED), now=NOW)
    m = db.scalars(select(Move)).one()
    assert (note.kind, note.scope_key, m.note_id, m.status) == ("stock_note", "UNH", note.id, "explained")


def test_refresh_works_for_a_small_move_too(db):
    setup_day(db, {"AAA": 0.4}, -0.3)
    note = notes.refresh_stock(db, "AAA", FakeBrave(), FakeFetcher(), client=fake(parsed=NOTHING), now=NOW)
    assert note.content["return_pct"] == 0.4 and db.scalars(select(Move)).first() is None


def test_refresh_of_an_unknown_ticker_does_nothing(db):
    assert notes.refresh_stock(db, "NOPE", FakeBrave(), FakeFetcher(), client=fake(parsed=NOTHING), now=NOW) is None
