"""Fetch EDGAR financial figures. Usage: python -m jobs.fundamentals [TICKER ...] [--all]

With no tickers, fetches only stocks that have no figures yet. --all refetches everyone."""

import sys

from tracker.data.edgar import EdgarClient
from tracker.data.fundamentals import refresh_fundamentals
from tracker.db import create_tables, session_scope


def main(argv: list[str]) -> None:
    create_tables()
    tickers = [a.upper() for a in argv if not a.startswith("--")] or None
    with session_scope() as s:
        out = refresh_fundamentals(s, EdgarClient(), tickers, only_missing="--all" not in argv and not tickers)
        empty = sorted(t for t, n in out.items() if n == 0)
        print(f"fetched {len(out)} companies, {sum(out.values())} rows; no figures yet for: {empty}")


if __name__ == "__main__":
    main(sys.argv[1:])
