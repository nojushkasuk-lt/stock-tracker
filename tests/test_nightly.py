"""Nightly job (no price data): figures for new reports, profile updates, upgrades without double batches;
weekly listings-only universe run."""

from contextlib import contextmanager
from datetime import date, datetime

from test_batches import FakeClient, _universe
from test_llm import NOW, db  # noqa: F401
from test_profiles import FakeFetcher
from tracker import config
from tracker.ai import profiles
from tracker.data.filings import missing_figures
from tracker.models import AiOutput, Filing, Fundamental, Universe, User, UserWatchlist


def _stock(db, ticker, active=True):
    db.add(Universe(ticker=ticker, cik="1", name=ticker, industry="Retail", active=active, updated_at=NOW))
    db.flush()


def _filing(db, ticker, acc, form="10-Q", filed=datetime(2026, 11, 10)):
    db.add(Filing(accession=acc, ticker=ticker, form=form, filed_at=filed, url=f"https://sec/{acc}.htm", processed_at=NOW))


def _figure(db, ticker, acc):
    db.add(Fundamental(ticker=ticker, metric="Revenues", period_end=date(2026, 9, 30), duration_days=91,
                       fiscal_period="Q3", form="10-Q", value=1.0, unit="USD", accession=acc, filed_at=date(2026, 11, 10)))


def test_recent_reports_without_their_figures_are_refetched(db):
    for t in ("HAS", "NEW", "OLD", "EIGHTK", "GONE"):
        _stock(db, t, active=t != "GONE")
    _filing(db, "HAS", "has-q3"); _figure(db, "HAS", "has-q3")  # figures from this report are in
    _filing(db, "NEW", "new-q3"); _figure(db, "NEW", "new-q2")  # only last quarter's figures
    _filing(db, "OLD", "old-q2", filed=datetime(2026, 8, 1))  # outside the window: stop retrying
    _filing(db, "EIGHTK", "e-8k", form="8-K")  # an earnings 8-K carries no XBRL statements
    _filing(db, "GONE", "gone-q3")  # left the universe
    db.flush()
    assert missing_figures(db, now=NOW) == ["NEW"]


def test_stocks_in_an_open_batch_are_not_sent_again(db):
    _universe(db, 2)
    c = FakeClient()
    assert profiles.submit_first_profiles(db, FakeFetcher(), client=c, now=NOW, log=lambda *_: None)
    assert profiles.in_open_batches(db) == {"S01", "S02"}
    assert profiles.submit_first_profiles(db, FakeFetcher(), client=c, now=NOW, log=lambda *_: None) is None


def test_upgrade_targets_skip_stocks_already_waiting_in_a_batch(db):
    _universe(db, 2)
    db.add(User(email="a@x.com", created_at=NOW))
    db.flush()
    for t in ("S01", "S02"):
        db.add(AiOutput(kind="profile", scope_key=t, model=config.MODEL_ROUTINE, input_hash=t, content={"about": []},
                        sources=[], created_at=NOW))
        db.add(UserWatchlist(email="a@x.com", ticker=t, added_at=NOW))
    db.flush()
    assert profiles.upgrade_targets(db) == ["S01", "S02"]
    profiles.submit_first_profiles(db, FakeFetcher(), tickers=["S01"], force=True, client=FakeClient(), now=NOW,
                                   log=lambda *_: None)
    assert profiles.upgrade_targets(db) == ["S02"]


def _run_nightly(db, monkeypatch, queue_result):
    import jobs.nightly as n

    calls = []

    @contextmanager
    def scope():
        yield db

    monkeypatch.setattr(n, "session_scope", scope)
    monkeypatch.setattr(n, "create_tables", lambda: None)
    monkeypatch.setattr(n, "EdgarClient", lambda: "edgar")
    monkeypatch.setattr(n, "FilingFetcher", lambda e: "fetcher")
    monkeypatch.setattr(n, "load_universe", lambda s: 0)
    monkeypatch.setattr(n, "check_filings", lambda s, e: calls.append("filings") or {"NEW": ["10-Q"]})
    monkeypatch.setattr(n, "missing_figures", lambda s: ["NEW"])
    monkeypatch.setattr(n, "refresh_fundamentals", lambda s, e, t=None, only_missing=True:
                        calls.append(("figures", t, only_missing)) or {})
    monkeypatch.setattr(n.profiles, "process_queue", lambda s, f: calls.append("profiles") or queue_result)
    monkeypatch.setattr(n.profiles, "upgrade_targets", lambda s: ["IBM"])
    monkeypatch.setattr(n.profiles, "submit_first_profiles", lambda *a, **k: calls.append(("upgrade", k["tickers"])) or "b1")
    n.main()
    return calls


def test_nightly_refreshes_figures_before_writing_profiles_then_upgrades(db, monkeypatch):
    calls = _run_nightly(db, monkeypatch, {"NEW": "profile 7"})
    assert calls == ["filings", ("figures", ["NEW"], False), ("figures", None, True), "profiles", ("upgrade", ["IBM"])]


def test_nightly_sends_no_upgrade_batch_once_the_budget_stops_it(db, monkeypatch):
    calls = _run_nightly(db, monkeypatch, {"NEW": "stopped: monthly budget reached"})
    assert calls[-1] == "profiles"


def test_weekly_listings_only_run_never_asks_for_market_caps(db, monkeypatch):
    import jobs.universe as u

    @contextmanager
    def scope():
        yield db

    def no_provider(*a, **k):
        raise AssertionError("listings-only must not need a price provider")

    seen = []
    monkeypatch.setattr(u, "session_scope", scope)
    monkeypatch.setattr(u, "create_tables", lambda: None)
    monkeypatch.setattr(u, "EdgarClient", lambda: "edgar")
    monkeypatch.setattr(u, "discover_new_listings", lambda s, e, known: seen.append(known) or [])
    monkeypatch.setattr(u, "get_provider", no_provider)
    monkeypatch.setattr(u, "refresh_universe", no_provider)
    u.main(["--listings-only"])
    assert seen and "AAPL" in seen[0]  # the CSV seed was loaded, then new listings were checked


def test_a_failed_upgrade_batch_keeps_the_profiles_written_before_it(db, monkeypatch):
    import jobs.nightly as n
    from tracker.ai import llm

    committed = []

    @contextmanager
    def scope():
        yield db
        committed.append(True)  # session_scope commits only when the block finishes without an error

    def fail(*a, **k):
        raise llm.BudgetExceeded("batch would pass the budget")

    _run_nightly(db, monkeypatch, {"NEW": "profile 7"})  # sets the other stubs
    monkeypatch.setattr(n, "session_scope", scope)
    monkeypatch.setattr(n.profiles, "submit_first_profiles", fail)
    n.main()  # no exception: the upgrade stop is reported, not raised
    assert len(committed) == 4  # every step finished; the profile updates were committed before the upgrade
