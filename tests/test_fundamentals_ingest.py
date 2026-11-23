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


def test_ifrs_filer_keeps_reporting_currency_only_and_gets_metrics():
    def f(end, val, start=None, form="20-F", filed="2026-04-15"):
        return fact(end, val, start=start, filed=filed, form=form)
    cf = {"facts": {"ifrs-full": {
        "Revenue": {"units": {"TWD": [f("2025-12-31", 3800.0, "2025-01-01"), f("2024-12-31", 2900.0, "2024-01-01")],
                              "USD": [f("2025-12-31", 120.0, "2025-01-01")]}},  # convenience translation: dropped
        "ProfitLossFromOperatingActivities": {"units": {"TWD": [f("2025-12-31", 1900.0, "2025-01-01")]}},
        "ProfitLossAttributableToOwnersOfParent": {"units": {"TWD": [f("2025-12-31", 1700.0, "2025-01-01")]}},
        "DilutedEarningsLossPerShare": {"units": {"TWD/shares": [f("2025-12-31", 65.0, "2025-01-01")],
                                                  "USD/shares": [f("2025-12-31", 2.0, "2025-01-01")]}},
        "CashAndCashEquivalents": {"units": {"TWD": [f("2025-12-31", 2500.0)]}},
        "Borrowings": {"units": {"TWD": [f("2025-12-31", 1000.0)]}},
        "DepreciationAndAmortisationExpense": {"units": {"TWD": [f("2025-12-31", 600.0, "2025-01-01")]}},
    }}}
    rows = extract_rows("TSM", cf, today=date(2026, 11, 1))
    assert {r["unit"] for r in rows} == {"TWD", "TWD/shares"} and all(r["metric"].startswith("ifrs:") for r in rows)

    class Row:
        def __init__(self, d):
            self.__dict__.update(d)
    m = compute_metrics([Row(r) for r in rows], "Semiconductors", today=date(2026, 11, 1))
    assert m.currency == "TWD" and m.revenue_ttm == 3800.0 and m.eps_diluted_ttm == 65.0
    assert round(m.operating_margin, 3) == 0.5 and round(m.revenue_growth_yoy, 3) == 0.31
    assert m.net_debt == 1000.0 - 2500.0 and round(m.net_debt_to_ebitda, 3) == round(-1500 / 2500, 3)
    old = compute_metrics([Row(r) for r in rows], "Semiconductors", today=date(2028, 6, 1))
    assert old.revenue_ttm is None and "too old" in old.notes["revenue"]
