"""Profiles.

  python -m jobs.profiles                 process queued filings for covered stocks (one call each)
  python -m jobs.profiles --first         one batch: first profiles for every stock that has none (top 30 Sonnet, rest Haiku)
  python -m jobs.profiles --upgrade       one batch: Sonnet profiles for followed stocks that only have a Haiku one
  python -m jobs.profiles --collect       save the results of finished batches
"""

import argparse

from sqlalchemy import select

from tracker.ai import profiles
from tracker.data.edgar import EdgarClient
from tracker.data.filing_text import FilingFetcher
from tracker.db import create_tables, session_scope
from tracker.models import AiBatch


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--first", action="store_true")
    ap.add_argument("--upgrade", action="store_true")
    ap.add_argument("--collect", action="store_true")
    ap.add_argument("--sonnet-top", type=int, default=30)
    ap.add_argument("--tickers", nargs="*")
    a = ap.parse_args(argv)
    create_tables()
    with session_scope() as s:
        if a.collect:
            pending = list(s.scalars(select(AiBatch).where(AiBatch.collected_at.is_(None))))
            for b in pending:
                for t, outcome in profiles.collect_profiles(s, b.id).items():
                    print(f"{t}: {outcome}")
            if not pending:
                print("no batches waiting")
            return
        fetcher = FilingFetcher(EdgarClient())
        if a.first or a.upgrade:
            if a.upgrade:
                targets = profiles.upgrade_targets(s)
                print(f"upgrade to Sonnet: {targets or 'none'}")
                bid = profiles.submit_first_profiles(s, fetcher, sonnet_top=10_000, tickers=targets, force=True) if targets else None
            else:
                bid = profiles.submit_first_profiles(s, fetcher, sonnet_top=a.sonnet_top, tickers=a.tickers)
            print(f"batch: {bid or 'nothing to send'}" + ("  (collect with: python -m jobs.profiles --collect)" if bid else ""))
            return
        results = profiles.process_queue(s, fetcher, limit=a.limit)
    for ticker, outcome in results.items():
        print(f"{ticker}: {outcome}")
    if not results:
        print("no queued filings for covered stocks")


if __name__ == "__main__":
    main()
