"""The universe: the 100 largest US companies. config/universe.csv seeds it; refresh_universe keeps it current."""

import csv
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker import config
from tracker.models import Universe

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
CSV_PATH = CONFIG_DIR / "universe.csv"
CANDIDATES_PATH = CONFIG_DIR / "candidates.csv"
UNCLASSIFIED = "Unclassified"


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def load_universe(session: Session, path: Path = CSV_PATH) -> int:
    """Seed from the CSV: insert tickers that are missing. Never updates or deletes existing rows.

    After the first load the refresh job owns rank, demo flag and active flag.
    Returns the number of rows inserted.
    """
    existing = set(session.scalars(select(Universe.ticker)))
    added = 0
    for r in read_csv(path):
        if r["ticker"] in existing:
            continue
        session.add(
            Universe(
                ticker=r["ticker"],
                cik=r["cik"].zfill(10),
                name=r["name"],
                industry=r["industry"] or UNCLASSIFIED,
                region=r.get("region") or "US",
                market_cap_rank=int(r["rank"]),
                is_demo=r["is_demo"].strip().lower() == "true",
                active=True,
                updated_at=_now(),
            )
        )
        added += 1
    session.flush()
    return added


@dataclass
class RefreshResult:
    entered: list[str] = field(default_factory=list)
    exited: list[str] = field(default_factory=list)
    demo_in: list[str] = field(default_factory=list)
    demo_out: list[str] = field(default_factory=list)
    no_market_cap: list[str] = field(default_factory=list)
    unclassified: list[str] = field(default_factory=list)


def refresh_universe(
    session: Session,
    market_caps: dict[str, float],
    candidates: list[dict],
    size: int | None = None,
    demo_size: int | None = None,
    exit_rank: int | None = None,
) -> RefreshResult:
    """Re-rank by market cap. Entries join at rank <= size; members only leave below exit_rank.

    Exits are soft: active=False. Followers keep the stock, nobody new can add it (and it loses the demo flag).
    Tickers without a market cap this run keep their previous status.
    """
    size = size or config.UNIVERSE_SIZE
    demo_size = demo_size or config.DEMO_SIZE
    exit_rank = exit_rank or config.UNIVERSE_EXIT_RANK

    rows = {u.ticker: u for u in session.scalars(select(Universe))}
    cand = {c["ticker"]: c for c in candidates}
    res = RefreshResult()

    pool = set(rows) | set(cand)
    ranked = sorted((t for t in pool if market_caps.get(t)), key=lambda t: -market_caps[t])
    rank_of = {t: i + 1 for i, t in enumerate(ranked)}
    res.no_market_cap = sorted(t for t in pool if not market_caps.get(t))

    # Incumbents keep their seat while they stay within exit_rank (or have no data this run).
    kept = [
        t for t, u in rows.items()
        if u.active and (t not in rank_of or rank_of[t] <= exit_rank)
    ]
    # Overfull (e.g. a bad seed): the best-ranked `size` incumbents stay; unranked ones sort last.
    kept.sort(key=lambda t: rank_of.get(t, float("inf")))
    kept = kept[:size]
    # Newcomers fill vacancies only, best rank first, and must be inside the top `size`.
    vacancies = size - len(kept)
    newcomers = [t for t in ranked if t not in kept and rank_of[t] <= size][:max(vacancies, 0)]
    member_set = set(kept) | set(newcomers)

    now = _now()
    for t in pool:
        in_set = t in member_set
        rank = rank_of.get(t)
        demo = in_set and rank is not None and rank <= demo_size
        u = rows.get(t)
        if u is None:
            if not in_set:
                continue
            c = cand[t]
            u = Universe(
                ticker=t, cik=c["cik"].zfill(10), name=c["name"],
                industry=c.get("industry") or UNCLASSIFIED, region="US",
                market_cap_rank=rank, is_demo=demo, active=True, updated_at=now,
            )
            session.add(u)
            res.entered.append(t)
            if u.industry == UNCLASSIFIED:
                res.unclassified.append(t)
            if demo:
                res.demo_in.append(t)
            continue
        if in_set and not u.active:
            res.entered.append(t)
        if not in_set and u.active:
            res.exited.append(t)
        if demo and not u.is_demo:
            res.demo_in.append(t)
        if not demo and u.is_demo:
            res.demo_out.append(t)
        u.active, u.is_demo = in_set, demo
        if rank is not None:
            u.market_cap_rank = rank
        u.updated_at = now
    session.flush()
    for k in ("entered", "exited", "demo_in", "demo_out", "unclassified"):
        getattr(res, k).sort()
    return res
