"""Closing-price series for the custom chart. Never written to the database (AGENTS.md rule 13).

Returns None when no chart provider is allowed (prod by default): the UI then shows the TradingView widgets.
"""

import threading
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from tracker import config

Point = tuple[date, float]


class ChartProvider(Protocol):
    def daily_closes(self, ticker: str) -> list[Point]: ...


@dataclass(frozen=True)
class ChartSeries:
    ticker: str
    points: list[Point]  # daily closes, oldest first
    intraday: dict[str, list[tuple[int, float]]] = field(default_factory=dict)  # "1D"/"1W" -> (epoch s, close)


def get_chart_provider(name: str | None = None) -> ChartProvider | None:
    name = name or config.CHART_PROVIDER
    if name == "none":
        return None
    if name == "yfinance_dev":
        from tracker.data.providers.yfinance_dev import YFinanceDev

        return YFinanceDev()  # raises if APP_ENV=prod
    raise ValueError(f"Unknown CHART_PROVIDER {name!r}")


_cache: dict[str, tuple[float, ChartSeries]] = {}
_lock = threading.Lock()


def get_chart_series(ticker: str, provider: ChartProvider | None = None, now=time.monotonic) -> ChartSeries | None:
    """Closing prices for one ticker, cached in memory. None if charts are off or there is too little data."""
    provider = provider or get_chart_provider()
    if provider is None:
        return None
    t = now()
    with _lock:
        hit = _cache.get(ticker)
        if hit and t - hit[0] < config.CHART_CACHE_SECONDS:
            return hit[1]
    try:
        points = provider.daily_closes(ticker)
    except Exception:
        return None
    if len(points) < 2:
        return None
    intraday: dict[str, list[tuple[int, float]]] = {}
    fetch = getattr(provider, "intraday", None)
    if fetch:
        try:
            intraday = {k: v for k, v in fetch(ticker).items() if len(v) >= 2}
        except Exception:
            intraday = {}  # intraday is optional: the longer ranges still work
    series = ChartSeries(ticker, points, intraday)
    with _lock:
        _cache[ticker] = (t, series)
    return series
