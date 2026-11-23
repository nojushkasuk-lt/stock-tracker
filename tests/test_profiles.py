"""Filing sections, profile sources and the profile queue. No network, no real model."""

from datetime import date, datetime

import pytest
from sqlalchemy import select

from test_llm import NOW, db, fake  # noqa: F401
from tracker.ai import profiles
from tracker.ai.citations import Claim
from tracker.ai.profiles import Point, ProfileOut
from tracker.analysis.metrics import Metrics
from tracker.data import filing_text as ft
from tracker.models import AiOutput, Filing, Universe, User, UserWatchlist

FILLER = "The company sells things to members. " * 80

HTML_10K = f"""<html><body><div style="display:none">dei:EntityRegistrantName Hidden XBRL header</div>
<p>Table of Contents</p><table><tr><td>Item 1.</td><td>Business</td><td>3</td></tr>
<tr><td>Item 1A.</td><td>Risk Factors</td><td>9</td></tr><tr><td>Item 7.</td><td>MD&amp;A</td><td>20</td></tr></table>
<p>PART I</p><p>Item 1. Business</p><p>{FILLER}</p>
<p>Item 1A. Risk Factors</p><p>Tariffs could raise costs. {FILLER}</p><p>Item 1B. Unresolved Staff Comments</p><p>None.</p>
<p>Item 7. Management&#8217;s Discussion and Analysis</p><p>Net sales increased 8%. {FILLER}</p>
<p>Item 7A. Quantitative and Qualitative Disclosures</p><p>Item 8. Financial Statements</p></body></html>"""


def test_html_to_text_drops_hidden_xbrl_header_and_keeps_blocks():
    t = ft.html_to_text(HTML_10K)
    assert "Hidden XBRL" not in t and "Management’s Discussion" in t
    assert "\nItem 1A. Risk Factors\n" in t


def test_10k_sections_skip_the_table_of_contents():
    secs = {s.key: s for s in ft.periodic_sections(ft.html_to_text(HTML_10K), "10-K", "u")}
    assert set(secs) == {"business", "risk_factors", "mdna"}
    assert secs["business"].text.startswith("Item 1. Business") and "Tariffs" not in secs["business"].text
    assert secs["risk_factors"].text.startswith("Item 1A. Risk Factors") and "Unresolved" not in secs["risk_factors"].text
    assert "Net sales increased 8%" in secs["mdna"].text and "Item 8" not in secs["mdna"].text


def test_item_1_does_not_match_item_10_or_1a():
    text = "Item 10. Directors\n" + FILLER + "\nItem 1A. Risks\n" + FILLER
    assert ft.section(text, "1", ["2"]) is None


def test_long_sections_are_cut_with_a_visible_marker():
    out = ft.cap("line\n" * 1000, 1000)
    assert len(out) < 1100 and "section cut here" in out


BASE = "https://www.sec.gov/Archives/edgar/data/109198/000010919826000058"
INDEX_PAGE = """<table><tr><td>1</td><td>8-K</td><td><a href="/ix?doc=/Archives/x/tjx-20261118.htm">tjx-20261118.htm</a></td><td>8-K</td></tr>
<tr><td>2</td><td>EX-99.1</td><td><a href="/Archives/edgar/data/109198/000010919826000058/tjxq3fy27earningspressrele.htm">tjxq3</a></td>
<td>EX-99.1</td></tr></table>"""


class FakeEdgar:
    def __init__(self, index_page=INDEX_PAGE, names=()):
        self.index_page, self.names = index_page, names

    def get_json(self, url):
        assert url == f"{BASE}/index.json"
        return {"directory": {"item": [{"name": n} for n in self.names]}}

    def get_text(self, url):
        if url.endswith("-index.htm"):
            assert url == f"{BASE}/0000109198-26-000058-index.htm"
            return self.index_page
        return f"<p>Release at {url.rsplit('/', 1)[1]}: revenue was $10.0 billion.</p>"


def test_fetcher_finds_the_earnings_release_by_exhibit_type():
    [sec] = ft.FilingFetcher(FakeEdgar()).sections("8-K", "2.02,9.01", f"{BASE}/tjx-20261118.htm")
    assert sec.key == "earnings_release" and sec.url == f"{BASE}/tjxq3fy27earningspressrele.htm"
    assert sec.text == "Release at tjxq3fy27earningspressrele.htm: revenue was $10.0 billion."


def test_fetcher_falls_back_to_an_ex99_file_name():
    edgar = FakeEdgar(index_page="<table></table>", names=["x-20261102.htm", "a8-kex991q4.htm", "x.xsd"])
    [sec] = ft.FilingFetcher(edgar).sections("8-K", "2.02", f"{BASE}/x-20261102.htm")
    assert sec.url == f"{BASE}/a8-kex991q4.htm"


def test_metrics_text_formats_numbers_the_model_can_quote():
    m = Metrics(as_of=date(2026, 8, 30), revenue_ttm=269.1e9, revenue_growth_yoy=0.078, operating_margin=0.036,
                net_margin=0.029, eps_diluted_ttm=18.21, net_debt_to_ebitda=-0.6)
    assert profiles.metrics_text(m) == (
        "Computed from SEC filings (as of 2026-08-30): revenue TTM $269.1B; revenue growth YoY 7.8%; operating "
        "margin 3.6%; net margin 2.9%; diluted EPS TTM $18.21; net debt/EBITDA -0.6x (net cash).")
    assert profiles.metrics_text(Metrics()) is None


# ---- queue ----------------------------------------------------------------------------------------

def pt(title, text, ids=("K1",)):
    return Point(title=title, text=text, source_ids=list(ids))


GOOD = ProfileOut(about=[Claim(text="Costco operated 914 warehouses.", source_ids=["K1"])],
                  business=[pt("Warehouse model", "Costco operated 914 warehouses.")],
                  strategy_and_trajectory=[pt("More warehouses", "It plans 30 net new warehouses.")],
                  bull_case=[pt("Sales growth", "Net sales increased 8%.")],
                  bear_case=[pt("Tariff risk", "Tariffs could raise costs.")])


class FakeFetcher:
    def __init__(self):
        self.calls = []

    def sections(self, form, items, url):
        self.calls.append(url)
        return [ft.Section("mdna", f"{form} MD&A", "We operated 914 warehouses. We plan 30 net new warehouses. "
                           "Net sales increased 8%. Tariffs could raise costs.", url)]


def add(db, ticker, demo=False):
    db.add(Universe(ticker=ticker, cik="1", name=ticker.title(), industry="Retail", is_demo=demo, updated_at=NOW))


def queue(db, ticker, acc, form="10-Q", filed=datetime(2026, 11, 20), items=None):
    db.add(Filing(accession=acc, ticker=ticker, form=form, items=items, filed_at=filed, url=f"https://sec/{acc}.htm"))


@pytest.fixture
def setup(db):
    add(db, "COST", demo=True)
    add(db, "WMT")
    add(db, "TGT")
    db.add(User(email="a@example.com", created_at=NOW))
    db.flush()
    db.add(UserWatchlist(email="a@example.com", ticker="TGT", added_at=NOW))
    queue(db, "COST", "c-old", form="8-K", items="2.02", filed=datetime(2026, 11, 1))
    queue(db, "COST", "c-new")
    queue(db, "WMT", "w1")
    queue(db, "TGT", "t1")
    db.flush()
    return db


def status(db):
    return {f.accession: f.processed_at is not None for f in db.scalars(select(Filing))}


def test_queue_writes_newest_filing_per_covered_stock_only(setup):
    db, fetch = setup, FakeFetcher()
    out = profiles.process_queue(db, fetch, client=fake(parsed=GOOD), now=NOW)
    assert set(out) == {"COST", "TGT"} and all(v.startswith("profile") for v in out.values())
    assert sorted(fetch.calls) == ["https://sec/c-new.htm", "https://sec/t1.htm"]
    assert status(db) == {"c-old": True, "c-new": True, "w1": False, "t1": True}  # WMT waits for a follower
    row = db.scalars(select(AiOutput).where(AiOutput.scope_key == "COST")).one()
    assert row.kind == "profile" and row.sources == [{"id": "K1", "url": "https://sec/c-new.htm", "outlet": "SEC EDGAR"}]


def test_second_profile_sees_the_first_as_previous(setup):
    db = setup
    profiles.process_queue(db, FakeFetcher(), client=fake(parsed=GOOD), now=NOW)
    queue(db, "COST", "c-next", filed=datetime(2026, 11, 22))
    db.flush()
    c = fake(parsed=GOOD)
    profiles.process_queue(db, FakeFetcher(), client=c, now=NOW)
    assert "[P0] kind=own" in c.messages.parse_calls[0]["messages"][0]["content"]


def test_budget_stop_leaves_filings_queued(setup, monkeypatch):
    from tracker import config
    monkeypatch.setattr(config, "MONTHLY_BUDGET_USD", 0.0)
    out = profiles.process_queue(setup, FakeFetcher(), client=fake(parsed=GOOD), now=NOW)
    assert list(out.values())[0].startswith("stopped") and len(out) == 1
    assert status(setup)["c-new"] is False and status(setup)["t1"] is False


def test_rejected_output_marks_filing_done_and_keeps_old_profile(setup):
    bad = ProfileOut(about=[Claim(text="Invented.", source_ids=["Z1"])])
    out = profiles.process_queue(setup, FakeFetcher(), client=fake(parsed=bad), now=NOW)
    assert all(v.startswith("no profile") for v in out.values())
    assert status(setup)["c-new"] is True and setup.scalars(select(AiOutput)).first() is None


def test_network_error_leaves_filing_queued(setup):
    class Broken(FakeFetcher):
        def sections(self, *a):
            raise ConnectionError("EDGAR down")
    out = profiles.process_queue(setup, Broken(), client=fake(parsed=GOOD), now=NOW)
    assert all(v.startswith("error") for v in out.values()) and status(setup)["c-new"] is False


def test_build_sources_orders_previous_metrics_then_filing():
    secs = [ft.Section("mdna", "10-Q Item 2 MD&A", "text", "https://sec/x.htm")]
    ids = [s.id for s in profiles.build_sources(None, Metrics(revenue_ttm=1e9), secs)]
    assert ids == ["M1", "K1"]
    ref = profiles.build_sources(None, None, secs, reference=("Founded in 1976.", "https://en.wikipedia.org/wiki/X"))
    assert [(s.id, s.kind) for s in ref] == [("K1", "primary"), ("W1", "reference")]


def test_points_are_checked_title_and_text_together():
    from tracker.ai.citations import Source
    src = [Source(id="K1", kind="primary", text="Net sales increased 8%.", label="10-K")]
    out = ProfileOut(about=[Claim(text="Net sales increased 8%.", source_ids=["K1"])],
                     business=[pt("Sales up 8%", "Net sales increased 8%."), pt("Sales up 12%", "Net sales increased 8%.")],
                     bull_case=[pt("Growth", "Net sales increased 8%.")], bear_case=[pt("Risk", "Net sales increased 8%.")])
    kept, checked = profiles.validate(out, src)
    assert [p.title for p in kept.business] == ["Sales up 8%"]       # 12% appears nowhere in the input
    assert any("12" in d.reason for d in checked.dropped)


def test_profile_without_a_required_section_is_rejected():
    from tracker.ai.citations import Source
    src = [Source(id="K1", kind="primary", text="Net sales increased 8%.", label="10-K")]
    out = ProfileOut(about=[Claim(text="Net sales increased 8%.", source_ids=["K1"])], business=[pt("Growth", "Net sales increased 8%.")])
    assert profiles.validate(out, src)[0] is None


def test_wikipedia_lead_and_condensed_history():
    from tracker.data import wikipedia
    text = "Lead text.\n\n== History ==\n\n=== 1976–1984 ===\n" + "Early. " * 400 + "\n=== 2007–2011 ===\nThe iPhone.\n\n== Products ==\nMac."
    out = wikipedia.lead_and_history(text, max_chars=3000)
    assert out.startswith("Lead text.") and "1976–1984: Early." in out and "2007–2011: The iPhone." in out
    assert "Mac." not in out and len(out) <= 3000
