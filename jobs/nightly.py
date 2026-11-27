"""Nightly (weekdays): new SEC reports -> fresh figures -> updated profiles. Needs no price data.

  python -m jobs.nightly

1. save finished profile batches (first profiles and Sonnet upgrades sent earlier);
2. check EDGAR for new filings of every active stock (a new 10-Q, 10-K or earnings 8-K is queued);
3. refetch the figures of stocks with a recent report whose figures we don't have yet;
4. write the profile update for queued reports of covered stocks (Sonnet, one call each);
5. send one batch upgrading covered stocks that only have a Haiku profile.

AI steps stop at the monthly budget (rule 6). Replaces the filings part of jobs/daily.py, which also needs
a licensed daily-returns provider and stays off (rule 13).
"""

from sqlalchemy import select

from tracker.ai import llm, profiles
from tracker.data.edgar import EdgarClient
from tracker.data.filing_text import FilingFetcher
from tracker.data.filings import check_filings, missing_figures
from tracker.data.fundamentals import refresh_fundamentals
from tracker.data.universe import load_universe
from tracker.db import create_tables, session_scope
from tracker.models import AiBatch


def main() -> None:
    create_tables()
    edgar = EdgarClient()
    with session_scope() as s:
        for b in list(s.scalars(select(AiBatch).where(AiBatch.collected_at.is_(None)))):
            for t, outcome in profiles.collect_profiles(s, b.id).items():
                print(f"batch {b.id}: {t}: {outcome}")
        print(f"universe: {load_universe(s)} new rows")
    with session_scope() as s:  # commit what EDGAR gave us before any model call
        new = check_filings(s, edgar)
        print(f"filings: new reports for {sorted(new) or 'none'}")
        stale = missing_figures(s)
        if stale:
            out = refresh_fundamentals(s, edgar, stale, only_missing=False)
            print(f"figures: refetched {stale} ({sum(out.values())} rows)")
        fetched = refresh_fundamentals(s, edgar)  # companies with no figures at all yet (new entrants)
        if fetched:
            print(f"figures: first fetch for {sorted(fetched)}")
    fetcher = FilingFetcher(edgar)
    with session_scope() as s:  # commit paid-for profiles before the upgrade step
        results = profiles.process_queue(s, fetcher)
        for t, outcome in results.items():
            print(f"profile update: {t}: {outcome}")
        if not results:
            print("profile updates: none queued for covered stocks")
    if any(o.startswith("stopped") for o in results.values()):
        return  # budget reached or the API is down: no upgrade batch tonight
    with session_scope() as s:
        targets = profiles.upgrade_targets(s)
        try:
            bid = profiles.submit_first_profiles(s, fetcher, sonnet_top=10_000, tickers=targets, force=True) if targets else None
        except (llm.BudgetExceeded, llm.LLMUnavailable) as e:
            print(f"Sonnet upgrades: stopped ({e})")
            return
        print(f"Sonnet upgrades: {targets or 'none'}" + (f" (batch {bid})" if bid else ""))


if __name__ == "__main__":
    main()
