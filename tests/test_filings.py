from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker.data.filings import (check_filings, is_profile_trigger, needs_new_figures, parse_submissions,
                                  record_filings)
from tracker.db import create_tables, make_engine
from tracker.models import Filing, Universe


def sub(*rows):
    keys = ["accessionNumber", "form", "items", "acceptanceDateTime", "filingDate", "reportDate", "primaryDocument"]
    return {"filings": {"recent": {k: [r[i] for r in rows] for i, k in enumerate(keys)}}}


OLD = ("0000320193-24-000001", "10-K", "", "2024-11-01T16:00:00.000Z", "2024-11-01", "2024-09-28", "aapl-2024.htm")
Q = ("0000320193-26-000010", "10-Q", "", "2026-08-01T20:30:00.000Z", "2026-08-01", "2026-06-27", "aapl-q3.htm")
FORM4 = ("0000320193-26-000011", "4", "", "2026-08-02T10:00:00.000Z", "2026-08-02", "", "x.xml")
NEW_10K = ("0000320193-26-000020", "10-K", "", "2026-10-31T20:30:00.000Z", "2026-10-31", "2026-09-26", "aapl-2026.htm")
EARN = ("0000320193-26-000021", "8-K", "2.02,9.01", "2026-10-30T20:31:00.000Z", "2026-10-30", "2026-10-30", "ex99.htm")
OTHER8K = ("0000320193-26-000022", "8-K", "5.02", "2026-11-05T12:00:00.000Z", "2026-11-05", "2026-11-05", "x.htm")


@pytest.fixture
def db(tmp_path):
    e = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    create_tables(e)
    with Session(e) as s:
        s.add(Universe(ticker="AAPL", cik="0000320193", name="Apple", industry="X", updated_at=datetime(2026, 1, 1)))
        s.flush()
        yield s


def test_parse_keeps_our_forms_and_builds_urls_and_utc_times():
    rows = parse_submissions(320193, sub(Q, FORM4, EARN))
    assert [r["form"] for r in rows] == ["10-Q", "8-K"]
    assert rows[0]["url"] == "https://www.sec.gov/Archives/edgar/data/320193/000032019326000010/aapl-q3.htm"
    assert rows[0]["filed_at"] == datetime(2026, 8, 1, 20, 30) and rows[1]["items"] == "2.02,9.01"


def test_profile_triggers():
    assert is_profile_trigger("10-Q", None) and is_profile_trigger("10-K", "")
    assert is_profile_trigger("8-K", "2.02,9.01") and not is_profile_trigger("8-K", "5.02")


def test_first_check_is_a_baseline_then_only_new_reports_are_queued(db):
    now = datetime(2026, 8, 10)
    assert record_filings(db, "AAPL", parse_submissions(320193, sub(Q, OLD)), now=now) == []
    stored = {f.accession: f for f in db.scalars(select(Filing))}
    assert set(stored) == {Q[0]}  # the 2024 10-K is older than the baseline window
    assert stored[Q[0]].processed_at is not None  # baseline rows are never queued

    new = record_filings(db, "AAPL", parse_submissions(320193, sub(Q, NEW_10K, EARN, OTHER8K)), now=datetime(2026, 11, 6))
    assert sorted(f.form for f in new) == ["10-K", "8-K"]  # the 5.02 8-K is stored but not queued
    assert db.scalar(select(Filing).where(Filing.accession == OTHER8K[0])).processed_at is not None
    assert record_filings(db, "AAPL", parse_submissions(320193, sub(Q, NEW_10K, EARN, OTHER8K))) == []  # idempotent


def test_check_filings_and_which_companies_need_new_figures(db):
    class FakeEdgar:
        def __init__(self, payload):
            self.payload = payload

        def submissions(self, cik):
            return self.payload

    check_filings(db, FakeEdgar(sub(Q)))  # baseline
    new = check_filings(db, FakeEdgar(sub(Q, EARN)))
    assert list(new) == ["AAPL"] and needs_new_figures(new) == []  # an earnings 8-K alone: no new XBRL figures
    new = check_filings(db, FakeEdgar(sub(Q, EARN, NEW_10K)))
    assert needs_new_figures(new) == ["AAPL"]


def test_old_filings_outside_the_window_are_never_queued_on_later_checks(db):
    record_filings(db, "AAPL", parse_submissions(320193, sub(Q, OLD)), now=datetime(2026, 8, 10))  # baseline
    new = record_filings(db, "AAPL", parse_submissions(320193, sub(Q, OLD, NEW_10K)), now=datetime(2026, 11, 1))
    assert [f.accession for f in new] == [NEW_10K[0]]  # the 2024 10-K stays ignored
