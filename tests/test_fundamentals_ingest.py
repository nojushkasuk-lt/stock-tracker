from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker.analysis.metrics import compute_metrics
from tracker.data.fundamentals import extract_rows, store_rows
from tracker.db import create_tables, make_engine
from tracker.models import Fundamental, Universe

REV = "RevenueFromContractWithCustomerExcludingAssessedTax"


def fact(end, val, start=None, filed="2026-02-01", form="10-K", fp="FY", accn="a-1"):
    d = {"end": end, "val": val, "filed": filed, "form": form, "fp": fp, "accn": accn}
    if start:
        d["start"] = start
    return d


FACTS = {"facts": {"us-gaap": {
    REV: {"units": {"USD": [
        fact("2025-12-31", 1000, "2025-01-01"),
        fact("2025-12-31", 1010, "2025-01-01", filed="2026-05-01", form="10-Q", fp="Q1", accn="a-2"),  # restated, later
        fact("2025-12-31", 999, "2025-01-01", form="8-K"),  # not a 10-K/10-Q: ignored
        fact("2005-12-31", 5, "2005-01-01"),  # too old: dropped
    ]}},
    "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [fact("2025-12-31", 70)]}},
    "SomeTagWeDoNotUse": {"units": {"USD": [fact("2025-12-31", 1)]}},
}}}


def test_extract_keeps_only_our_tags_forms_and_recent_years_and_latest_filing_wins():
    rows = extract_rows("X", FACTS, today=date(2026, 6, 1))
    by = {(r["metric"], r["period_end"], r["duration_days"]): r for r in rows}
    assert set(r["metric"] for r in rows) == {REV, "CashAndCashEquivalentsAtCarryingValue"}
    assert by[(REV, date(2025, 12, 31), 364)]["value"] == 1010  # restatement wins
    assert by[("CashAndCashEquivalentsAtCarryingValue", date(2025, 12, 31), 0)]["value"] == 70  # instant: duration 0
    assert len(rows) == 2


def test_store_replaces_rows_and_roundtrips_into_metrics(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    create_tables(engine)
    with Session(engine) as s:
        s.add(Universe(ticker="X", cik="1".zfill(10), name="X", industry="Software", updated_at=date(2026, 1, 1)))
        s.flush()
        rows = extract_rows("X", FACTS, today=date(2026, 6, 1))
        assert store_rows(s, "X", rows) == 2
        assert store_rows(s, "X", rows) == 2  # idempotent: replaced, not duplicated
        stored = list(s.scalars(select(Fundamental)))
        assert len(stored) == 2
        m = compute_metrics(stored, industry="Software")
        assert m.revenue_ttm == 1010 and m.as_of == date(2025, 12, 31)


def test_predecessor_history_is_merged_and_latest_filing_wins():
    from tracker.data.fundamentals import merge_rows, read_predecessors

    old = [{"metric": REV, "period_end": date(2020, 12, 31), "duration_days": 365, "filed_at": date(2021, 2, 1), "value": 1.0},
           {"metric": REV, "period_end": date(2024, 12, 31), "duration_days": 365, "filed_at": date(2025, 2, 1), "value": 2.0}]
    new = [{"metric": REV, "period_end": date(2024, 12, 31), "duration_days": 365, "filed_at": date(2026, 2, 1), "value": 2.5}]
    merged = {(r["period_end"]): r["value"] for r in merge_rows(old, new)}
    assert merged == {date(2020, 12, 31): 1.0, date(2024, 12, 31): 2.5}
    assert read_predecessors()["XOM"] == [34088]
