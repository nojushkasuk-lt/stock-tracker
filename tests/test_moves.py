"""Move detection and the market -> industry -> stock ladder (AGENTS.md rule 14)."""

from datetime import date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker.analysis import moves
from tracker.analysis.moves import classify_day, market_level
from tracker.db import create_tables, make_engine
from tracker.models import DailyReturn, MarketDay, Move, Universe

IND = {"NVDA": "Semis", "AMD": "Semis", "MU": "Semis", "AVGO": "Semis", "INTC": "Semis",
       "ORCL": "Software", "CRM": "Software", "MSFT": "Software", "ADBE": "Software",
       "UNH": "Health", "LLY": "Pharma"}
ALL = set(IND)


def day(returns, spy, covered=ALL, demo=frozenset()):
    base = {t: 0.0 for t in IND}
    base.update(returns)
    return {c.ticker: c for c in classify_day(base, spy, IND, set(covered), set(demo))}


def test_market_levels():
    assert [market_level(x) for x in (1.9, -2.0, 2.9, -3.0, 4.4)] == ["none", "alert", "alert", "major", "major"]


def test_small_moves_are_not_candidates_but_demo_stocks_use_3_percent():
    assert day({"UNH": -4.9}, 0.1) == {}
    assert day({"UNH": -3.1}, 0.1, demo={"UNH"})["UNH"].scope == "stock"


def test_single_stock_move_gets_its_own_scope():
    c = day({"UNH": -10.2}, -0.3)["UNH"]
    assert c.scope == "stock" and c.market_return_pct == -0.3


def test_stock_with_the_market_on_an_alert_day_is_market_scope():
    assert day({"ORCL": -5.5}, -3.6)["ORCL"].scope == "market"


def test_stock_far_from_the_market_on_an_alert_day_is_still_its_own_story():
    assert day({"ORCL": -8.5}, -3.6)["ORCL"].scope == "stock"  # residual 4.9 >= 3


def test_no_market_scope_when_the_index_is_calm_even_if_residual_is_small():
    assert day({"ORCL": -5.0}, -1.9)["ORCL"].scope == "stock"


def test_industry_scope_needs_three_peers_averaging_3_percent():
    c = day({"NVDA": -7.0, "AMD": -5.5, "MU": -7.6, "AVGO": -4.0, "INTC": -3.0}, -1.0)
    assert c["NVDA"].scope == "industry"
    assert c["NVDA"].industry_return_pct == pytest.approx((-5.5 - 7.6 - 4.0 - 3.0) / 4)


def test_stock_far_from_its_industry_is_stock_scope():
    c = day({"NVDA": -14.0, "AMD": -4.0, "MU": -4.0, "AVGO": -4.0, "INTC": -4.0}, -1.0)
    assert c["NVDA"].scope == "stock"


def test_too_few_peers_never_makes_an_industry():
    c = day({"UNH": -6.0}, -0.5)
    assert c["UNH"].industry_return_pct is None and c["UNH"].scope == "stock"


def test_industry_needs_peers_to_actually_move():
    c = day({"ORCL": -6.0, "CRM": -1.0, "MSFT": -0.5, "ADBE": -1.0}, -0.5)
    assert c["ORCL"].scope == "stock"


def test_uncovered_stocks_count_as_peers_but_get_no_move():
    c = day({"NVDA": -7.0, "AMD": -6.0, "MU": -6.5, "AVGO": -5.5}, -1.0, covered={"NVDA"})
    assert set(c) == {"NVDA"} and c["NVDA"].scope == "industry"


def test_forty_stocks_falling_together_give_one_market_scope_and_no_stock_searches():
    tickers = [f"S{i:02d}" for i in range(40)]
    industries = {t: f"Ind{i % 8}" for i, t in enumerate(tickers)}
    returns = {t: -5.0 - (i % 5) * 0.4 for i, t in enumerate(tickers)}  # -5.0 to -6.6
    out = classify_day(returns, -4.4, industries, set(tickers), set())
    assert len(out) == 40
    assert {c.scope for c in out} == {"market"}


# ---- database -------------------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    e = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    create_tables(e)
    with Session(e) as s:
        for t, ind in IND.items():
            s.add(Universe(ticker=t, cik="1", name=t, industry=ind, is_demo=(t == "UNH"), updated_at=datetime(2026, 1, 1)))
        yield s


D = date(2026, 11, 18)


def add_returns(db, returns, spy):
    db.add(DailyReturn(ticker="SPY", date=D, return_pct=spy))
    for t in IND:
        db.add(DailyReturn(ticker=t, date=D, return_pct=returns.get(t, 0.0)))
    db.flush()


def test_load_and_record_a_day(db):
    add_returns(db, {"UNH": -10.2, "LLY": 4.0}, -0.3)
    d = moves.load_day(db, D, covered={"UNH", "LLY"})
    assert d.level == "none" and [c.ticker for c in d.moves] == ["UNH"]  # LLY 4% < 5%, not demo
    [m] = moves.record_day(db, d)
    assert (m.ticker, m.scope, m.status, float(m.return_pct)) == ("UNH", "stock", "pending", -10.2)
    assert db.get(MarketDay, D).level == "none"


def test_recording_twice_keeps_status_and_note(db):
    add_returns(db, {"UNH": -10.2}, -0.3)
    d = moves.load_day(db, D, covered={"UNH"})
    [m] = moves.record_day(db, d)
    m.status = "explained"
    moves.record_day(db, d)
    assert db.scalars(select(Move)).one().status == "explained"


def test_no_spy_return_means_no_day(db):
    assert moves.load_day(db, D, covered=ALL) is None
