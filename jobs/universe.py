"""Weekly job: re-rank the universe by market cap (entries, exits, demo top 20)."""

from tracker.data.prices import get_provider
from tracker.data.universe import CANDIDATES_PATH, load_universe, read_csv, refresh_universe
from tracker.db import create_tables, session_scope
from tracker.models import Universe
from sqlalchemy import select


def main() -> None:
    create_tables()
    with session_scope() as s:
        load_universe(s)
        candidates = read_csv(CANDIDATES_PATH)
        tickers = sorted(set(s.scalars(select(Universe.ticker))) | {c["ticker"] for c in candidates})
        caps = get_provider().market_caps(tickers)
        print(f"market caps for {len(caps)}/{len(tickers)} tickers")
        res = refresh_universe(s, caps, candidates)
        for k, v in vars(res).items():
            print(f"{k}: {v}")


if __name__ == "__main__":
    main()
