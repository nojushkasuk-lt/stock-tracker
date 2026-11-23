"""Index funds and ETFs shown on the Market page (config/markets.csv). Only their daily changes are stored."""

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / "config" / "markets.csv"
GROUPS = ["US indexes", "International", "Bonds", "Commodities", "Sectors"]
DEFAULT_FOLLOWED = ["SPY", "QQQ", "VGK"]


@dataclass(frozen=True)
class Fund:
    ticker: str
    name: str
    group: str
    tracks: str
    issuer: str
    tv_symbol: str


@lru_cache(maxsize=1)
def load(path: Path = PATH) -> tuple[Fund, ...]:
    with path.open(newline="") as f:
        funds = tuple(Fund(**{k: (v or "").strip() for k, v in row.items()}) for row in csv.DictReader(f))
    bad = [x for x in funds if x.group not in GROUPS]
    if bad:
        raise ValueError(f"Unknown market group for {[x.ticker for x in bad]}")
    return funds


def by_ticker() -> dict[str, Fund]:
    return {f.ticker: f for f in load()}


def tickers() -> list[str]:
    return [f.ticker for f in load()]
