"""Process queued profile updates (filings that data/filings.py detected). python -m jobs.profiles [--limit N]"""

import argparse

from tracker.ai.profiles import process_queue
from tracker.data.edgar import EdgarClient
from tracker.data.filing_text import FilingFetcher
from tracker.db import create_tables, session_scope


def main(limit: int | None = None) -> None:
    create_tables()
    with session_scope() as s:
        results = process_queue(s, FilingFetcher(EdgarClient()), limit=limit)
    for ticker, outcome in results.items():
        print(f"{ticker}: {outcome}")
    if not results:
        print("no queued filings for covered stocks")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    main(ap.parse_args().limit)
