"""Transient Tiingo Starter snapshots for the watchlist aggregate and news lookups."""

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
class NotableMove:
    direction: str
    session: date
    previous_session: date


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


def _snapshot_moves(symbols: set[str]) -> list[_Move]:
    token = config.TIINGO_API_KEY
    if not symbols or not token:
        return []
    global _cached_moves, _refresh_at
    with _lock:
        if monotonic() >= _refresh_at:
            _cached_moves = _fetch(token)
            _refresh_at = monotonic() + REFRESH_SECONDS
        return [_cached_moves[symbol] for symbol in symbols if symbol in _cached_moves]


def notable_move(ticker: str) -> NotableMove | None:
    """Expose only the direction and session of a move that meets the coverage threshold."""
    moves = _snapshot_moves({ticker.upper().replace("-", ".")})
    if moves and abs(moves[0].percent) >= config.MOVE_THRESHOLD_PCT:
        move = moves[0]
        return NotableMove("rose" if move.percent > 0 else "fell", move.session, move.previous_session)
    return None


def watchlist_change(tickers: list[str]) -> WatchlistChange | None:
    """Return only the aggregate, and only for two or more comparable quotes."""
    symbols = {ticker.upper().replace("-", ".") for ticker in tickers}
    if len(symbols) < 2:
        return None
    moves = _snapshot_moves(symbols)
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


def closing_changes(tickers: list[str], session: date) -> dict[str, float]:
    """Fetch official split-adjusted closes for an internal, transient news trigger."""
    changes = {}
    with httpx.Client(headers={"Authorization": f"Token {config.TIINGO_API_KEY}"}, timeout=8) as client:
        for ticker in dict.fromkeys(tickers):
            symbol = ticker.replace(".", "-")
            response = client.get(
                f"https://api.tiingo.com/tiingo/daily/{symbol}/prices",
                params={"startDate": (session - timedelta(days=10)).isoformat(), "endDate": session.isoformat()},
            )
            if response.status_code in (400, 404):
                continue
            response.raise_for_status()
            try:
                closes = sorted((date.fromisoformat(row["date"][:10]), float(row["adjClose"]))
                                for row in response.json())
            except (KeyError, TypeError, ValueError):
                continue
            if len(closes) < 2 or closes[-1][0] != session or closes[-2][0] >= session:
                continue
            previous, latest = closes[-2][1], closes[-1][1]
            if 0 < previous < math.inf and 0 < latest < math.inf:
                change = (latest / previous - 1) * 100
                if math.isfinite(change):
                    changes[ticker] = change
    return changes
