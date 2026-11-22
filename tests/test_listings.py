from datetime import datetime

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker.data.edgar import EdgarClient, EdgarConfigError, is_domestic_filer
from tracker.data.listings import discover_new_listings, discovered_candidates
from tracker.data.universe import refresh_universe, read_pins
from tracker.db import create_tables, make_engine
from tracker.models import ListingSeen, Universe


class FakeEdgar:
    def __init__(self, rows, forms):
        self.rows, self.forms, self.calls = rows, forms, []

    def tickers_exchange(self):
        return self.rows

    def submissions(self, cik):
        self.calls.append(cik)
        return {"sic": "7372", "filings": {"recent": {"form": self.forms[cik]}}}


def row(t, cik, ex="Nasdaq"):
    return {"cik": cik, "name": t + " Inc", "ticker": t, "exchange": ex}


def _db(tmp_path):
    e = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    create_tables(e)
    return Session(e)


def test_domestic_filer_rules():
    sub = lambda f: {"filings": {"recent": {"form": f}}}
    assert is_domestic_filer(sub(["10-Q", "8-K"]))
    assert is_domestic_filer(sub(["424B4", "S-1"]))  # brand-new IPO
    assert not is_domestic_filer(sub(["20-F", "6-K"]))  # foreign issuer (ADR)
    assert not is_domestic_filer(sub(["424B4", "F-1", "6-K"]))
    assert not is_domestic_filer(sub(["4", "3"]))


def test_first_run_is_a_baseline_with_no_candidates(tmp_path):
    with _db(tmp_path) as s:
        edgar = FakeEdgar([row("AAA", 1), row("BBB", 2)], {})
        assert discover_new_listings(s, edgar, known=set()) == []
        assert edgar.calls == []
        assert {l.ticker for l in s.scalars(select(ListingSeen))} == {"AAA", "BBB"}


def test_new_listing_flagged_foreign_and_otc_ignored(tmp_path):
    with _db(tmp_path) as s:
        discover_new_listings(s, FakeEdgar([row("AAA", 1)], {}), known=set())
        edgar = FakeEdgar(
            [row("AAA", 1), row("NEWCO", 5), row("ADR", 6, "NYSE"), row("PINK", 7, "OTC")],
            {5: ["424B4", "S-1"], 6: ["20-F", "6-K"], 7: ["10-K"]},
        )
        assert discover_new_listings(s, edgar, known=set()) == ["NEWCO"]
        assert edgar.calls == [5, 6]  # OTC never checked
        assert [c["ticker"] for c in discovered_candidates(s)] == ["NEWCO"]
        # Seen once: not flagged again next week.
        assert discover_new_listings(s, edgar, known=set()) == []


def test_edgar_client_needs_contact_and_sends_user_agent():
    with pytest.raises(EdgarConfigError):
        EdgarClient(name="x", email="")
    seen = {}

    def handler(req):
        seen["ua"] = req.headers["user-agent"]
        return httpx.Response(200, json={"fields": ["cik", "name", "ticker", "exchange"], "data": [[1, "A", "A", "NYSE"]]})

    c = EdgarClient(client=httpx.Client(transport=httpx.MockTransport(handler)), name="tracker", email="me@example.com")
    assert c.tickers_exchange() == [{"cik": 1, "name": "A", "ticker": "A", "exchange": "NYSE"}]
    assert seen["ua"] == "tracker me@example.com"


def _seed(s, n=4):
    for i in range(1, n + 1):
        s.add(Universe(ticker=f"T{i}", cik="1".zfill(10), name=f"Co {i}", industry="X",
                       market_cap_rank=i, is_demo=False, active=True, updated_at=datetime(2026, 1, 1)))
    s.flush()


def test_pin_keeps_a_stock_that_would_exit(tmp_path):
    with _db(tmp_path) as s:
        _seed(s)
        caps = {f"T{i}": float(100 - i) for i in range(1, 5)}
        caps["T1"] = 1.0  # T1 collapses to last place
        refresh_universe(s, caps, [], size=3, demo_size=1, exit_rank=3, pins={"T1"})
        assert s.get(Universe, "T1").active is True
        assert sum(u.active for u in s.query(Universe)) == 3  # the pin takes a seat inside `size`


def test_pin_enters_from_candidates_without_a_market_cap(tmp_path):
    with _db(tmp_path) as s:
        _seed(s)
        cand = [{"ticker": "IPO", "cik": "9", "name": "IPO Co", "industry": "", "sic_code": "7372"}]
        refresh_universe(s, {f"T{i}": float(100 - i) for i in range(1, 5)}, cand, size=4, demo_size=1, exit_rank=4, pins={"IPO"})
        u = s.get(Universe, "IPO")
        assert u.active and not u.is_demo and u.sic_code == "7372"


def test_pins_file_is_header_only_by_default():
    assert read_pins() == set()
