"""Universe: spot new listings, re-rank by market cap (entries, exits, demo top 20).

  python -m jobs.universe                   full re-rank (needs a price provider with market caps)
  python -m jobs.universe --listings-only   weekly: load new CSV rows and flag new US listings as candidates;
                                            the ranking stays as it is (frozen while there is no licensed
                                            market-cap source; re-ranked by hand a few times a year)
"""

import argparse

from sqlalchemy import select

from tracker.data.global_listings import listings as global_listings
from tracker.data.edgar import EdgarClient
from tracker.data.listings import discover_new_listings, discovered_candidates
from tracker.data.prices import get_provider
from tracker import config
from tracker.data.universe import (
    CANDIDATES_PATH, INTERNATIONAL_PATH, load_universe, read_csv, read_pins, refresh_universe, rerank_members,
)
from tracker.db import create_tables, session_scope
from tracker.models import Universe


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--listings-only", action="store_true", help="no re-rank: new CSV rows and new listings only")
    listings_only = ap.parse_args(argv).listings_only
    create_tables()
    with session_scope() as s:
        print(f"universe: {load_universe(s)} new rows from the CSV")
        csv_cands = read_csv(CANDIDATES_PATH)
        known = set(s.scalars(select(Universe.ticker))) | {c["ticker"] for c in csv_cands}
        new = discover_new_listings(s, EdgarClient(), known)
        print(f"new US listings flagged as candidates: {new}")
        if listings_only:
            print("ranking unchanged (--listings-only)")
            return
        pool = {c["ticker"]: c for c in csv_cands}
        pool.update({c["ticker"]: c for c in discovered_candidates(s)})
        intl = read_csv(INTERNATIONAL_PATH)
        tickers = sorted((known | set(pool) | {c["ticker"] for c in intl}) - set(global_listings()))
        caps = get_provider().market_caps(tickers)
        print(f"market caps for {len(caps)}/{len(tickers)} tickers")
        pins = read_pins()
        for region, cands in [("US", list(pool.values())), *[(r, intl) for r in config.INTL_REGIONS]]:
            res = refresh_universe(s, caps, cands, pins=pins, region=region)
            print(f"[{region}]", {k: v for k, v in vars(res).items() if v})
        rerank_members(s, caps)


if __name__ == "__main__":
    main()
