"""EDGAR XBRL companyfacts -> fundamentals table (only the tags in analysis.metrics.CONCEPTS).

US companies report in US GAAP (10-K / 10-Q). Foreign filers report in US GAAP or IFRS (20-F / 6-K), often in their
own currency: only facts in the reporting currency are kept (TSMC also tags US dollar convenience translations)."""

import csv
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from tracker.analysis.metrics import ALL_TAGS, IFRS
from tracker.data.edgar import EdgarClient
from tracker.models import Fundamental, Universe

PREDECESSORS_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "predecessors.csv"
FORMS = {"10-K", "10-Q", "20-F", "6-K"}
TAXONOMIES = {"us-gaap": "", "ifrs-full": IFRS}  # taxonomy -> prefix of the stored metric name
KEEP_YEARS = 10  # enough for 8 fiscal years of history plus the prior-year comparisons


def extract_rows(ticker: str, companyfacts: dict, today: date | None = None) -> list[dict]:
    """Rows for the tags we use. One row per (tag, period end, duration); the latest filing wins."""
    today = today or date.today()
    cutoff = today - timedelta(days=365 * KEEP_YEARS)
    facts_by_tax = companyfacts.get("facts", {})
    found = []
    for tax, prefix in TAXONOMIES.items():
        tags = facts_by_tax.get(tax, {})
        for name in ALL_TAGS:
            if name.startswith(IFRS) != bool(prefix):
                continue
            for unit, facts in tags.get(name.removeprefix(IFRS), {}).get("units", {}).items():
                found.append((name, unit, facts))
    ccy = _reporting_currency(found)
    best: dict[tuple, dict] = {}
    for tag, unit, facts in found:
        if _currency(unit) not in (None, ccy):
            continue  # another currency (convenience translation)
        for f in facts:
            if f.get("form") not in FORMS or "end" not in f or "val" not in f:
                continue
            end = date.fromisoformat(f["end"])
            if end < cutoff:
                continue
            duration = (end - date.fromisoformat(f["start"])).days if f.get("start") else 0
            filed = date.fromisoformat(f["filed"])
            key = (tag, end, duration)
            if key in best and best[key]["filed_at"] >= filed:
                continue
            best[key] = {
                "ticker": ticker, "metric": tag, "period_end": end, "duration_days": duration,
                "fiscal_period": f.get("fp") or "", "form": f["form"], "value": float(f["val"]),
                "unit": unit, "accession": f.get("accn", ""), "filed_at": filed,
            }
    return list(best.values())


def _currency(unit: str) -> str | None:
    """'TWD' or 'TWD/shares' -> 'TWD'; 'shares' or 'pure' -> None."""
    head = unit.split("/")[0]
    return head if len(head) == 3 and head.isupper() else None


def _reporting_currency(found: list[tuple]) -> str:
    """Currency of most annual-report money facts."""
    counts: dict[str, int] = {}
    for _, unit, facts in found:
        if (ccy := _currency(unit)) is not None:
            counts[ccy] = counts.get(ccy, 0) + sum(1 for f in facts if f.get("form") in ("10-K", "20-F"))
    return max(counts, key=lambda c: (counts[c], c == "USD")) if counts else "USD"


def read_predecessors(path: Path = PREDECESSORS_PATH) -> dict[str, list[int]]:
    """ticker -> CIKs of earlier registrants whose filings continue this company's history."""
    out: dict[str, list[int]] = {}
    if path.exists():
        with path.open(newline="") as f:
            for r in csv.DictReader(f):
                out.setdefault(r["ticker"], []).append(int(r["predecessor_cik"]))
    return out


def merge_rows(*row_sets: list[dict]) -> list[dict]:
    """Combine rows from several registrants; for the same period the latest filing wins."""
    best: dict[tuple, dict] = {}
    for rows in row_sets:
        for r in rows:
            k = (r["metric"], r["period_end"], r["duration_days"])
            if k not in best or r["filed_at"] > best[k]["filed_at"]:
                best[k] = r
    return list(best.values())


def store_rows(session: Session, ticker: str, rows: list[dict]) -> int:
    """Replace everything stored for the ticker (idempotent)."""
    session.execute(delete(Fundamental).where(Fundamental.ticker == ticker))
    session.add_all(Fundamental(**r) for r in rows)
    session.flush()
    return len(rows)


def refresh_fundamentals(session: Session, edgar: EdgarClient, tickers: list[str] | None = None,
                         only_missing: bool = True) -> dict[str, int]:
    """Fetch and store companyfacts. By default only tickers with no stored figures yet.

    Day 3 will make this filing-triggered (refetch when a new 10-Q/10-K appears).
    """
    q = select(Universe.ticker, Universe.cik).where(Universe.cik != "")
    if tickers:
        q = q.where(Universe.ticker.in_(tickers))
    have = set(session.scalars(select(Fundamental.ticker).distinct())) if only_missing else set()
    out: dict[str, int] = {}
    predecessors = read_predecessors()
    for ticker, cik in session.execute(q).all():
        if ticker in have:
            continue
        sets = [extract_rows(ticker, _facts(edgar, c)) for c in predecessors.get(ticker, [])]
        sets.append(extract_rows(ticker, _facts(edgar, int(cik))))
        rows = merge_rows(*sets)
        out[ticker] = store_rows(session, ticker, rows)
    return out


def _facts(edgar: EdgarClient, cik: int) -> dict:
    """companyfacts, or {} when the SEC has no XBRL figures for the company (404: e.g. a foreign filer that
    files its financial statements without XBRL)."""
    import httpx

    try:
        return edgar.companyfacts(cik)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {}
        raise


def last_updated(session: Session, ticker: str) -> date | None:
    return session.scalar(select(func.max(Fundamental.filed_at)).where(Fundamental.ticker == ticker))
