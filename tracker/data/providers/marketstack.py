"""Marketstack end-of-day provider (Basic plan: commercial use, 10,000 requests a month).

Only daily percent changes leave this module (AGENTS.md rule 13); closes stay inside `daily_returns`.
Marketstack counts one request per symbol per page, so requests are sized to fit one page of at most
1,000 rows: a few days for many symbols at once (the daily run), or one symbol at a time for backfills.

The access key travels in the query string (the only way Marketstack accepts it), so errors are re-raised
without the request URL: GitHub Actions logs of a public repository must never contain it.
"""

import math
import time
from datetime import date, timedelta

import httpx

from tracker import config

BASE_URL = "https://api.marketstack.com/v2/eod"
PAGE_ROWS = 1000       # Marketstack's maximum `limit`
MAX_SYMBOLS = 100      # per request
MIN_INTERVAL = 0.25    # seconds between requests (limit: 5 per second)


class MarketstackError(RuntimeError):
    pass


def _rows_per_symbol(start: date, end: date) -> int:
    """Upper bound on trading days in [start, end]: weekdays plus one."""
    days = (end - start).days + 1
    return days * 5 // 7 + 2


class Marketstack:
    def __init__(self, api_key: str | None = None, client: httpx.Client | None = None, pause: float = MIN_INTERVAL):
        self.key = api_key or config.MARKETSTACK_API_KEY
        if not self.key:
            raise MarketstackError("MARKETSTACK_API_KEY is not set")
        self.client = client or httpx.Client(timeout=30)
        self.pause = pause
        self.requests = 0  # symbols x pages, as Marketstack bills them

    def _get(self, params: dict) -> dict:
        for attempt in range(4):
            if self.requests:
                time.sleep(self.pause)
            try:
                r = self.client.get(BASE_URL, params={"access_key": self.key, **params})
            except httpx.HTTPError as exc:
                raise MarketstackError(f"request failed ({type(exc).__name__})") from None
            self.requests += len(params["symbols"].split(","))
            if r.status_code == 429 and attempt < 3:
                body = r.text.lower()
                if "quota" in body or "usage" in body:
                    raise MarketstackError("monthly request quota reached")
                time.sleep(1 + attempt)  # per-second rate limit: wait and retry
                continue
            try:
                body = r.json()
            except ValueError:
                raise MarketstackError(f"HTTP {r.status_code}, not JSON") from None
            if r.status_code != 200 or "error" in body:
                err = body.get("error") or {}
                code = err.get("code") if isinstance(err, dict) else None
                msg = (err.get("message") or err.get("info") or "") if isinstance(err, dict) else ""
                raise MarketstackError(f"HTTP {r.status_code} {code or ''} {msg[:160]}".strip())
            return body
        raise MarketstackError("rate limited")

    def closes(self, tickers: list[str], start: date, end: date | None = None) -> dict[str, list[tuple[date, float]]]:
        """Adjusted closes per ticker, oldest first. Internal: callers outside this module get percent changes."""
        end = end or date.today()
        per_batch = max(1, min(MAX_SYMBOLS, PAGE_ROWS // _rows_per_symbol(start, end)))
        out: dict[str, dict[date, float]] = {}
        wanted = list(dict.fromkeys(t.upper() for t in tickers))
        for i in range(0, len(wanted), per_batch):
            batch = wanted[i:i + per_batch]
            offset = 0
            while True:
                body = self._get({"symbols": ",".join(batch), "date_from": start.isoformat(),
                                  "date_to": end.isoformat(), "limit": PAGE_ROWS, "offset": offset, "sort": "ASC"})
                rows = body.get("data") or []
                for row in rows:
                    try:
                        sym = str(row["symbol"]).upper()
                        day = date.fromisoformat(str(row["date"])[:10])
                        close = row.get("adj_close")
                        close = float(close if close is not None else row["close"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if sym in batch and 0 < close < math.inf:
                        out.setdefault(sym, {})[day] = close
                page = body.get("pagination") or {}
                offset += len(rows)
                if not rows or offset >= int(page.get("total") or 0):
                    break
        return {t: sorted(series.items()) for t, series in out.items()}

    def daily_returns(self, tickers: list[str], start: date, end: date | None = None):
        # One extra week before `start` so the first day in range has its previous close.
        series = self.closes(tickers, start - timedelta(days=7), end)
        out = {}
        for t, closes in series.items():
            rets = [(d, (c / p - 1) * 100) for (_, p), (d, c) in zip(closes, closes[1:]) if d >= start]
            rets = [(d, r) for d, r in rets if math.isfinite(r)]
            if rets:
                out[t] = rets
        return out

    def market_caps(self, tickers: list[str]) -> dict[str, float]:
        """Not offered on the EOD plan. Empty: the weekly re-rank then keeps every current seat."""
        return {}
