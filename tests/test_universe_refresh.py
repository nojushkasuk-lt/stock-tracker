from datetime import datetime

from sqlalchemy.orm import Session

from tracker.data.universe import load_universe, refresh_universe
from tracker.db import create_tables, make_engine
from tracker.models import Universe


def _db(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    create_tables(engine)
    return Session(engine)


def _seed(s, n=6):
    for i in range(1, n + 1):
        s.add(Universe(ticker=f"T{i}", cik="1".zfill(10), name=f"Co {i}", industry="X",
                       market_cap_rank=i, is_demo=i <= 2, active=True, updated_at=datetime(2026, 1, 1)))
    s.flush()


def caps(order):
    """order[0] is the biggest."""
    return {t: float(1000 - i) for i, t in enumerate(order)}


def test_loader_seeds_only_missing_rows(tmp_path):
    with _db(tmp_path) as s:
        assert load_universe(s) == 100
        s.get(Universe, "AAPL").market_cap_rank = 77
        assert load_universe(s) == 0
        assert s.get(Universe, "AAPL").market_cap_rank == 77


def test_new_entrant_joins_and_weakest_member_exits(tmp_path):
    with _db(tmp_path) as s:
        _seed(s)  # T1..T6 all start active
        s.get(Universe, "T5").active = s.get(Universe, "T6").active = False  # members are T1..T4
        cand = [{"ticker": "NEW", "cik": "5", "name": "New Co", "industry": ""}]
        res = refresh_universe(s, caps(["NEW", "T1", "T2", "T3", "T4", "T5", "T6"]), cand,
                               size=4, demo_size=2, exit_rank=4)
        assert res.entered == ["NEW"] and res.exited == ["T4"] and res.unclassified == ["NEW"]
        assert s.get(Universe, "NEW").is_demo and s.get(Universe, "NEW").market_cap_rank == 1
        assert s.get(Universe, "T4").active is False and s.get(Universe, "T4").is_demo is False
        assert sum(u.active for u in s.query(Universe)) == 4  # stays at `size`


def test_exit_is_soft_row_kept(tmp_path):
    with _db(tmp_path) as s:
        _seed(s)
        refresh_universe(s, caps(["T6", "T5", "T4", "T3", "T2", "T1"]), [], size=3, demo_size=1, exit_rank=3)
        assert s.get(Universe, "T1") is not None and s.get(Universe, "T1").active is False


def test_buffer_stops_flip_flopping_at_the_boundary(tmp_path):
    with _db(tmp_path) as s:
        _seed(s)
        for t in ("T4", "T5", "T6"):
            s.get(Universe, t).active = False
        # T3 is a member, falls to rank 4 (size 3) but stays inside exit_rank 5: stays.
        cand = [{"ticker": "NEW", "cik": "5", "name": "N", "industry": "X"}]
        res = refresh_universe(s, caps(["T1", "T2", "NEW", "T3", "T4", "T5", "T6"]), cand,
                               size=3, demo_size=1, exit_rank=5)
        assert s.get(Universe, "T3").active is True
        assert res.entered == []  # no vacancy: the universe stays at `size`
        assert s.get(Universe, "NEW") is None


def test_demo_flag_follows_rank(tmp_path):
    with _db(tmp_path) as s:
        _seed(s)
        res = refresh_universe(s, caps(["T3", "T2", "T1", "T4", "T5", "T6"]), [], size=6, demo_size=1, exit_rank=6)
        assert s.get(Universe, "T3").is_demo and not s.get(Universe, "T1").is_demo
        assert res.demo_in == ["T3"] and res.demo_out == ["T1", "T2"]


def test_ticker_without_market_cap_keeps_status(tmp_path):
    with _db(tmp_path) as s:
        _seed(s)
        c = caps(["T1", "T2", "T3", "T4", "T5"])  # T6 missing
        res = refresh_universe(s, c, [], size=6, demo_size=2, exit_rank=6)
        assert res.no_market_cap == ["T6"] and s.get(Universe, "T6").active is True
