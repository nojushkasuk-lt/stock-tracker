"""Weekly: company key facts and logos from Wikidata.  python -m jobs.facts"""

from datetime import UTC, datetime

from sqlalchemy import select

from tracker.data import wikidata
from tracker.db import create_tables, get_engine, session_scope
from tracker.models import CompanyFacts, Universe


def save(session, facts_by_cik: dict[str, wikidata.Facts], now: datetime,
         facts_by_ticker: dict[str, wikidata.Facts] | None = None) -> int:
    n = 0
    for u in session.scalars(select(Universe)):
        f = facts_by_cik.get(u.cik) or (facts_by_ticker or {}).get(u.ticker.replace("-", "."))
        if f is None:
            continue
        row = session.get(CompanyFacts, u.ticker) or CompanyFacts(ticker=u.ticker)
        for k in ("qid", "logo_url", "ceo", "ceo_since", "headquarters", "country", "founded", "employees", "website", "wikipedia_url"):
            setattr(row, k, getattr(f, k))
        row.fetched_at = now
        session.add(row)
        n += 1
    return n


def main() -> None:
    create_tables(get_engine())
    with session_scope() as s:
        pairs = sorted((u.cik, u.ticker) for u in s.scalars(select(Universe).where(Universe.cik != "")))
    ciks = [c for c, _ in pairs]
    facts = wikidata.fetch(ciks)
    missing = [t.replace("-", ".") for c, t in pairs if c not in facts]
    by_ticker = wikidata.fetch_by_ticker(missing) if missing else {}
    with session_scope() as s:
        n = save(s, facts, datetime.now(UTC).replace(tzinfo=None), by_ticker)
    logos = sum(1 for f in [*facts.values(), *by_ticker.values()] if f.logo_url)
    print(f"Facts saved for {n} of {len(pairs)} companies ({logos} with a logo; {len(by_ticker)} matched by ticker).")


if __name__ == "__main__":
    main()
