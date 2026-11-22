"""Load config/universe.csv into the universe table (idempotent upsert)."""

import csv
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from tracker.models import Universe

CSV_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "universe.csv"


def read_universe_csv(path: Path = CSV_PATH) -> list[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def load_universe(session: Session, path: Path = CSV_PATH) -> int:
    """Insert or update every row of the CSV. Never deletes: followed tickers must keep existing."""
    now = datetime.now(UTC).replace(tzinfo=None)
    rows = read_universe_csv(path)
    for r in rows:
        session.merge(
            Universe(
                ticker=r["ticker"],
                cik=r["cik"].zfill(10),
                name=r["name"],
                industry=r["industry"],
                region=r.get("region") or "US",
                market_cap_rank=int(r["rank"]),
                is_demo=r["is_demo"].strip().lower() == "true",
                updated_at=now,
            )
        )
    session.flush()
    return len(rows)
