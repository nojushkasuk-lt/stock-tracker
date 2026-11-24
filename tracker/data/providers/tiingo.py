"""Transient Tiingo Starter snapshots for the licensed watchlist aggregate."""

import logging
import math
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from time import monotonic
from zoneinfo import ZoneInfo

import httpx

from tracker import config

SNAPSHOT_URL = "https://api.tiingo.com/tiingo/equity/intraday"
REFRESH_SECONDS = 15 * 60
NEW_YORK = ZoneInfo("America/New_York")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WatchlistChange:
    percent: float
    as_of: datetime
    covered: int


@dataclass(frozen=True)
class _Move:
    percent: float
    timestamp: datetime
    session: date
    previous_session: date


def _parse_move(row: dict) -> _Move | None:
    try:
        last = float(row["tngoLast"])
        close = float(row["prevClose"])
        timestamp = datetime.fromisoformat(row["timestamp"])
        previous = date.fromisoformat(row["prevDate"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if timestamp.tzinfo is None or not (0 < last < math.inf and 0 < close < math.inf):
        return None
    timestamp = timestamp.astimezone(NEW_YORK)
    # Tiingo rolls its previous-close baseline at 8 p.m. Eastern.
    session = (timestamp + timedelta(hours=4)).date()
    percent = (last / close - 1) * 100
    if previous >= session or not math.isfinite(percent):
        return None
    return _Move(percent, timestamp, session, previous)


def _fetch(token: str) -> dict[str, _Move]:
    try:
        url = httpx.URL(SNAPSHOT_URL)
        headers = {"Authorization": f"Token {token}"}
        for _ in range(3):
            response = httpx.get(str(url), headers=headers, timeout=8)
            if not response.has_redirect_location:
                break
            target = url.join(response.headers["Location"])
            if target.scheme != "https" or target.host != url.host or target.port != url.port:
                logger.warning("Tiingo snapshot redirected outside its API origin")
                return {}
            url = target
        response.raise_for_status()
        rows = response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("Tiingo snapshot returned HTTP %s", exc.response.status_code)
        return {}
    except (httpx.HTTPError, httpx.InvalidURL, ValueError) as exc:
        logger.warning("Tiingo snapshot failed (%s)", type(exc).__name__)
        return {}
    if not isinstance(rows, list):
        return {}
    moves = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(ticker := row.get("ticker"), str):
            continue
        if move := _parse_move(row):
            moves[ticker.upper()] = move
    return moves


_lock = threading.Lock()
_cached_moves: dict[str, _Move] = {}
_refresh_at = 0.0


def watchlist_change(tickers: list[str]) -> WatchlistChange | None:
    """Return only the aggregate, and only for two or more comparable quotes."""
    symbols = {ticker.upper().replace("-", ".") for ticker in tickers}
    token = config.TIINGO_API_KEY
    if len(symbols) < 2 or not token:
        return None

    global _cached_moves, _refresh_at
    with _lock:
        if monotonic() >= _refresh_at:
            _cached_moves = _fetch(token)
            _refresh_at = monotonic() + REFRESH_SECONDS
        moves = [_cached_moves[symbol] for symbol in symbols if symbol in _cached_moves]
    groups: dict[tuple[date, date], list[_Move]] = {}
    for move in moves:
        groups.setdefault((move.session, move.previous_session), []).append(move)
    if not groups:
        return None
    latest = groups[max(groups)]
    if len(latest) < 2:
        return None
    return WatchlistChange(math.fsum(move.percent / len(latest) for move in latest),
                           min(move.timestamp for move in latest), len(latest))
