"""Curated primary or reference listings outside the SEC-based universe."""

from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from tracker.data.universe import CONFIG_DIR, read_csv
from tracker.models import Universe


@lru_cache(maxsize=1)
def listings() -> dict[str, dict]:
    return {row["ticker"]: row for row in read_csv(CONFIG_DIR / "global_listings.csv")}


@lru_cache(maxsize=1)
def logo_files() -> dict[str, dict]:
    """Curated logos (config/logo_icons.csv): the Wikimedia Commons source file and its kind. symbol = the brand's
    symbol; word = a short wordmark shown whole; mark = the emblem or first letter cut from a long wordmark.
    The images are served from web/static/logos/<ticker>.png (':' becomes '_')."""
    return {row["ticker"]: row for row in read_csv(CONFIG_DIR / "logo_icons.csv")}


def seed_global_listings(session) -> None:
    """Register listings for watchlists, including on existing databases. Safe on concurrent startup."""
    insert = postgres_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    values = [
        {**{key: row[key] for key in ("ticker", "name", "industry", "country", "region")},
         "cik": "", "is_demo": False, "active": True, "updated_at": datetime.now(UTC).replace(tzinfo=None)}
        for row in listings().values()
    ]
    stmt = insert(Universe).values(values).on_conflict_do_nothing(index_elements=[Universe.ticker])
    session.execute(stmt)
