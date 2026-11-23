"""Refresh stored SEC filings for demo and followed stocks without running price or AI jobs."""

from tracker.data.edgar import EdgarClient
from tracker.data.filings import check_filings
from tracker.data.universe import covered_tickers
from tracker.db import session_scope


def main() -> None:
    with session_scope() as session:
        tickers = sorted(covered_tickers(session))
        if tickers:
            filings = check_filings(session, EdgarClient(), tickers)
            print(f"Checked {len(tickers)} covered stocks. New profile-triggering filings for {len(filings)}.")


if __name__ == "__main__":
    main()
