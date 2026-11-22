from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tracker.data.universe import load_universe
from tracker.db import create_tables, make_engine
from tracker.models import Universe, User, UserWatchlist


def test_load_is_idempotent_and_flags_top_20(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    create_tables(engine)
    with Session(engine) as s:
        assert load_universe(s) == 100
        assert load_universe(s) == 100
        s.commit()
        assert s.scalar(select(func.count()).select_from(Universe)) == 100
        assert s.scalar(select(func.count()).select_from(Universe).where(Universe.is_demo)) == 20
        assert s.get(Universe, "BRK-B").cik == "0001067983"


def test_reload_does_not_remove_followed_tickers(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    create_tables(engine)
    with Session(engine) as s:
        load_universe(s)
        s.add(User(email="a@b.c", created_at=datetime(2026, 1, 1)))
        s.add(UserWatchlist(email="a@b.c", ticker="AAPL", added_at=datetime(2026, 1, 1)))
        s.commit()
        load_universe(s)
        s.commit()
        assert s.get(Universe, "AAPL") is not None
