"""Live news links from the Brave News Search API, filtered to the outlets a user picked.

AGENTS.md rules 11 and 13: results are never written to the database. They live in a short in-memory cache
(NEWS_CACHE_SECONDS, under 1 hour) and only headline, outlet, link and time are shown, never article text.
Every real API call is counted in usage_log and stops at MONTHLY_SEARCH_CAP.
"""

import threading
import time
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tracker import config
from tracker.models import UsageLog

NEWS_URL = "https://api.search.brave.com/res/v1/news/search"
OUTLETS_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "outlets.toml"


@dataclass(frozen=True)
class Outlet:
    name: str
    domain: str
    paywall: bool


@dataclass(frozen=True)
class NewsLink:
    title: str
    url: str
    outlet: str
    domain: str
    published: datetime | None
    paywall: bool


class SearchCapReached(RuntimeError):
    pass


class NewsNotConfigured(RuntimeError):
    pass


def load_outlets(path: Path = OUTLETS_PATH) -> list[Outlet]:
    with path.open("rb") as f:
        data = tomllib.load(f)
    return [Outlet(o["name"], o["domain"].lower(), bool(o.get("paywall", False))) for o in data.get("outlet", [])]


def match_outlet(url: str, outlets: list[Outlet]) -> Outlet | None:
    """The outlet whose domain is the URL's host or a parent of it (www.reuters.com -> reuters.com)."""
    host = (urlparse(url).hostname or "").lower()
    for o in sorted(outlets, key=lambda o: -len(o.domain)):  # most specific first (finance.yahoo.com)
        if host == o.domain or host.endswith("." + o.domain):
            return o
    return None


def _parse_time(r: dict) -> datetime | None:
    raw = r.get("page_age")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo else dt


def parse_results(payload: dict) -> list[dict]:
    """Keep only what we display: title, url, time. (Descriptions are dropped: we never show article text.)"""
    out = []
    for r in payload.get("results", []):
        if r.get("title") and r.get("url"):
            out.append({"title": r["title"], "url": r["url"], "published": _parse_time(r)})
    return out


class BraveNews:
    def __init__(self, api_key: str | None = None, client: httpx.Client | None = None):
        self.api_key = api_key if api_key is not None else config.BRAVE_SEARCH_API_KEY
        if not self.api_key:
            raise NewsNotConfigured("Set BRAVE_SEARCH_API_KEY in .env")
        self._client = client or httpx.Client(timeout=20)

    def search(self, q: str, freshness: str = "pw", count: int = 50) -> list[dict]:
        r = self._client.get(
            NEWS_URL,
            params={"q": q, "freshness": freshness, "count": count, "search_lang": "en", "country": "us"},
            headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"},
        )
        r.raise_for_status()
        return parse_results(r.json())


# ---- monthly cap -------------------------------------------------------------------------------

def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def searches_this_month(session: Session, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC).replace(tzinfo=None)
    q = select(func.coalesce(func.sum(UsageLog.search_calls), 0)).where(UsageLog.created_at >= _month_start(now))
    return int(session.scalar(q))


def record_search(session: Session, job: str, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC).replace(tzinfo=None)
    session.add(UsageLog(created_at=now, job=job, model=None, search_calls=1, cost_usd=0.0))
    session.flush()


# ---- transient cache ---------------------------------------------------------------------------

_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def cached_search(session: Session, brave: BraveNews, q: str, freshness: str = "pw", job: str = "coverage",
                  now=time.monotonic) -> list[dict]:
    """One Brave query, shared by everyone for NEWS_CACHE_SECONDS. Only real API calls count toward the cap."""
    key, t = (q, freshness), now()
    with _lock:
        hit = _cache.get(key)
        if hit and t - hit[0] < min(config.NEWS_CACHE_SECONDS, 3599):
            return hit[1]
    if searches_this_month(session) >= config.MONTHLY_SEARCH_CAP:
        raise SearchCapReached(f"Monthly search cap of {config.MONTHLY_SEARCH_CAP} reached")
    results = brave.search(q, freshness)
    record_search(session, job)
    with _lock:
        # Drop expired entries so the cache never holds results longer than the limit.
        for k in [k for k, (ts, _) in _cache.items() if t - ts >= config.NEWS_CACHE_SECONDS]:
            del _cache[k]
        _cache[key] = (t, results)
    return results


def coverage_query(company: str, ticker: str) -> str:
    return f'"{company}" {ticker} stock'


def coverage_links(results: list[dict], outlets: list[Outlet], domains: set[str] | None = None,
                   limit: int | None = None) -> list[NewsLink]:
    """Filter to the chosen outlets (all configured outlets when none chosen), newest first, one link per URL."""
    allowed = [o for o in outlets if not domains or o.domain in domains]
    seen, out = set(), []
    for r in results:
        o = match_outlet(r["url"], allowed)
        if o is None or r["url"] in seen:
            continue
        seen.add(r["url"])
        out.append(NewsLink(r["title"], r["url"], o.name, o.domain, r["published"], o.paywall))
    out.sort(key=lambda n: n.published or datetime.min, reverse=True)
    return out[: limit or config.COVERAGE_RESULTS]
