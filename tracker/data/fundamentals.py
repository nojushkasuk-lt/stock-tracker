"""EDGAR XBRL companyfacts -> fundamentals table (only the tags in analysis.metrics.CONCEPTS)."""

import csv
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from tracker.analysis.metrics import ALL_TAGS
from tracker.data.edgar import EdgarClient
from tracker.models import Fundamental, Universe

PREDECESSORS_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "predecessors.csv"
FORMS = {"10-K", "10-Q"}
KEEP_YEARS = 10  # enough for 8 fiscal years of history plus the prior-year comparisons


def extract_rows(ticker: str, companyfacts: dict, today: date | None = None) -> list[dict]:
    """Rows for the tags we use. One row per (tag, period end, duration); the latest filing wins."""
    today = today or date.today()
    cutoff = today - timedelta(days=365 * KEEP_YEARS)
    gaap = companyfacts.get("facts", {}).get("us-gaap", {})
    best: dict[tuple, dict] = {}
    for tag in ALL_TAGS:
        for unit, facts in gaap.get(tag, {}).get("units", {}).items():
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
    q = select(Universe.ticker, Universe.cik)
    if tickers:
        q = q.where(Universe.ticker.in_(tickers))
    have = set(session.scalars(select(Fundamental.ticker).distinct())) if only_missing else set()
    out: dict[str, int] = {}
    predecessors = read_predecessors()
    for ticker, cik in session.execute(q).all():
        if ticker in have:
            continue
        sets = [extract_rows(ticker, edgar.companyfacts(c)) for c in predecessors.get(ticker, [])]
        sets.append(extract_rows(ticker, edgar.companyfacts(int(cik))))
        rows = merge_rows(*sets)
        out[ticker] = store_rows(session, ticker, rows)
    return out


def last_updated(session: Session, ticker: str) -> date | None:
    return session.scalar(select(func.max(Fundamental.filed_at)).where(Fundamental.ticker == ticker))
