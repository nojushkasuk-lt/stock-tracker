import re
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from tracker.db import create_tables, make_engine
from tracker.models import AiOutput, Base, Move, Universe


def _schema_tables() -> set[str]:
    sql = (Path(__file__).resolve().parent.parent / "schema.sql").read_text()
    return set(re.findall(r"CREATE TABLE (\w+)", sql))


def test_models_cover_every_table_in_schema_sql():
    assert set(Base.metadata.tables) == _schema_tables()


def test_create_tables_and_roundtrip(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    create_tables(engine)
    assert set(inspect(engine).get_table_names()) == _schema_tables()

    with Session(engine) as s:
        s.add(Universe(ticker="AAPL", cik="0000320193", name="Apple", industry="Technology",
                       market_cap_rank=1, is_demo=True, updated_at=datetime(2026, 1, 1)))
        out = AiOutput(kind="stock_note", scope_key="AAPL", model="m", input_hash="h",
                       content={"a": 1}, sources=[{"id": "s1"}], created_at=datetime(2026, 1, 1))
        s.add(out)
        s.flush()  # BigInteger PK must autoincrement on SQLite
        s.add(Move(ticker="AAPL", date=date(2026, 1, 2), return_pct=-6.1, scope="stock",
                   note_id=out.id, status="pending"))
        s.commit()
        assert out.id == 1
        assert s.get(Universe, "AAPL").region == "US"


def test_new_nullable_columns_are_added_to_existing_tables(tmp_path):
    from sqlalchemy import text

    from tracker.db import add_missing_columns

    engine = make_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as c:  # a table as it was before start_date existed
        c.execute(text("CREATE TABLE users (email TEXT PRIMARY KEY, created_at TIMESTAMP, last_login TIMESTAMP)"))
        c.execute(text("CREATE TABLE user_watchlist (email TEXT, ticker TEXT, added_at TIMESTAMP, PRIMARY KEY (email, ticker))"))
    create_tables(engine)
    assert "start_date" in {c["name"] for c in inspect(engine).get_columns("user_watchlist")}
    assert add_missing_columns(engine) == []  # idempotent
