from datetime import date, datetime

import pytest
from sqlalchemy.orm import Session

from tracker import services
from tracker.analysis.metrics import AnnualPoint, Metrics
from tracker.data.fundamentals import extract_rows, store_rows
from tracker.db import create_tables, make_engine
from tracker.models import Universe
from ui import financials as fin


def test_formatting():
    assert fin.money(478.83e9) == "$478.8B" and fin.money(5.105e9) == "$5.11B" and fin.money(1.2e12) == "$1.20T"
    assert fin.money(-42.46e9) == "-$42.5B" and fin.money(None) == "n/a" and fin.money(950) == "$950"
    assert fin.percent(0.3301) == "33.0%" and fin.percent(0.151, signed=True) == "+15.1%" and fin.percent(None) == "n/a"
    assert fin.multiple(1.724) == "1.72×" and fin.eps(8.98) == "$8.98" and fin.eps(None) == "n/a"
    assert "Sep 2026" in fin.as_of_text(date(2026, 9, 26)) and "No filed figures" in fin.as_of_text(None)


def test_cards_say_why_a_number_is_missing():
    m = Metrics(revenue_ttm=1e9, notes={"net_debt_to_ebitda": "Not meaningful for banks."})
    by = {c["label"]: c for c in fin.cards(m)}
    assert by["Net debt / EBITDA"]["value"] == "n/a" and "banks" in by["Net debt / EBITDA"]["help"]
    assert by["Revenue"]["delta"] is None
    approx = {c["label"]: c for c in fin.cards(Metrics(net_debt_to_ebitda=1.0, ebitda_basis="approx"))}
    assert "approximate" in approx["Net debt / EBITDA"]["help"]


def test_figure_handles_missing_margins_and_empty_history():
    assert fin.revenue_margin_figure([]) is None
    pts = [AnnualPoint(date(2024, 12, 31), 100e9, None, None), AnnualPoint(date(2025, 12, 31), 120e9, 0.3, "operating")]
    fig = fin.revenue_margin_figure(pts)
    assert len(fig.data) == 2 and list(fig.data[1].y) == [30.0]  # only the year that has a margin
    assert fin.revenue_margin_figure(pts[:1]).data[0].name == "Revenue" and len(fin.revenue_margin_figure(pts[:1]).data) == 1


def test_fiscal_year_label_uses_the_year_the_period_mostly_belongs_to():
    fig = fin.revenue_margin_figure([AnnualPoint(date(2026, 1, 3), 1e9, None, None)])  # 52/53-week year ending early Jan
    assert list(fig.data[0].x) == [2025]


def test_services_returns_financials_for_a_stored_company(tmp_path, monkeypatch):
    from contextlib import contextmanager

    engine = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    create_tables(engine)
    with Session(engine) as s:
        s.add(Universe(ticker="X", cik="1".zfill(10), name="X", industry="Software", updated_at=datetime(2026, 1, 1)))
        s.flush()
        facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
            {"start": "2025-01-01", "end": "2025-12-31", "val": 1000, "filed": "2026-02-01", "form": "10-K", "fp": "FY", "accn": "a"}]}}}}}
        store_rows(s, "X", extract_rows("X", facts, today=date(2026, 6, 1)))
        s.commit()

    @contextmanager
    def scope():
        with Session(engine) as s:
            yield s

    monkeypatch.setattr(services, "session_scope", scope)
    f = services.get_financials("x")
    assert f.metrics.revenue_ttm == 1000 and len(f.history) == 1
    assert services.get_financials("NOPE") is None
    with Session(engine) as s:
        s.add(Universe(ticker="Y", cik="", name="Y", industry="Software", updated_at=datetime(2026, 1, 1)))
        s.commit()
    assert services.get_financials("Y") is None  # no SEC figures: no empty cards
