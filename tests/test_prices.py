from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker.data import prices
from tracker.data.providers.yfinance_dev import ProviderNotAllowed, YFinanceDev
from tracker.db import create_tables, make_engine
from tracker.models import DailyReturn


def test_yfinance_dev_refuses_to_run_in_prod(monkeypatch):
    monkeypatch.setattr("tracker.config.APP_ENV", "prod")
    with pytest.raises(ProviderNotAllowed):
        YFinanceDev()


def test_yfinance_dev_allowed_locally(monkeypatch):
    monkeypatch.setattr("tracker.config.APP_ENV", "local")
    YFinanceDev()


def test_unknown_provider_rejected():
    with pytest.raises(ValueError):
        prices.get_provider("nope")


def test_store_returns_upserts(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    create_tables(engine)
    with Session(engine) as s:
        prices.store_returns(s, {"AAPL": [(date(2026, 1, 2), 1.5), (date(2026, 1, 3), -2.0)]})
        prices.store_returns(s, {"AAPL": [(date(2026, 1, 3), -2.5)]})
        s.commit()
        got = {r.date: r.return_pct for r in s.scalars(select(DailyReturn))}
        assert got == {date(2026, 1, 2): 1.5, date(2026, 1, 3): -2.5}
