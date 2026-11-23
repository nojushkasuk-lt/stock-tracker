"""Copy every table from one database to another (local SQLite -> Neon Postgres), in foreign-key order.

    python -m jobs.copy_db --to "$NEON_URL"            # from DATABASE_URL (default: local SQLite)
    python -m jobs.copy_db --to "$NEON_URL" --replace  # empty the target tables first

Refuses to write into tables that already have rows unless --replace is given.
"""

import argparse

from sqlalchemy import func, insert, select

from tracker.db import create_tables, make_engine
from tracker.models import Base

BATCH = 2_000


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", required=True, help="target database URL")
    ap.add_argument("--from", dest="src", default=None, help="source URL (default: DATABASE_URL)")
    ap.add_argument("--replace", action="store_true")
    a = ap.parse_args(argv)
    src, dst = make_engine(a.src), make_engine(a.to)
    create_tables(dst)
    tables = Base.metadata.sorted_tables  # parents before children
    with dst.begin() as d:
        busy = [t.name for t in tables if d.execute(select(func.count()).select_from(t)).scalar_one()]
        if busy and not a.replace:
            raise SystemExit(f"target already has rows in {busy}; use --replace to overwrite")
        for t in reversed(tables):
            d.execute(t.delete())
    for t in tables:
        n = 0
        with src.connect() as s, dst.begin() as d:
            rows = s.execute(select(t)).mappings()
            chunk = []
            for r in rows:
                chunk.append(dict(r))
                if len(chunk) >= BATCH:
                    d.execute(insert(t), chunk); n += len(chunk); chunk = []
            if chunk:
                d.execute(insert(t), chunk); n += len(chunk)
        print(f"{t.name}: {n}")
    if dst.dialect.name == "postgresql":  # move id sequences past the copied ids
        with dst.begin() as d:
            for t in tables:
                for c in t.columns:
                    if c.primary_key and c.autoincrement is True or (c.primary_key and str(c.type).upper().startswith("BIGINT")):
                        d.exec_driver_sql(f"SELECT setval(pg_get_serial_sequence('{t.name}', '{c.name}'), "
                                          f"COALESCE((SELECT MAX({c.name}) FROM {t.name}), 1))")


if __name__ == "__main__":
    main()
