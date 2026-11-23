"""Detect new 10-Q / 10-K / 8-K filings (US companies) and 20-F / 6-K filings (foreign filers) from EDGAR submissions.

A 6-K is kept only when it carries XBRL financial statements (half-year or quarterly results); the many other
6-Ks (press releases, meeting notices) are skipped.

The first check for a company records a baseline: older filings are stored as already processed so they never
flood the profile queue. After that, a new 10-Q, 10-K or earnings 8-K (item 2.02) is queued (processed_at NULL)
and a new 10-Q / 10-K triggers a refetch of that company's figures.
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker.data.edgar import EdgarClient
from tracker.models import Filing, Universe

FORMS = {"10-Q", "10-K", "8-K", "20-F", "6-K"}
PERIODIC = {"10-Q", "10-K", "20-F", "6-K"}  # reports with financial statements
ANNUAL = {"10-K", "20-F"}
INTERIM = {"10-Q", "6-K"}
BASELINE_DAYS = 400  # keep about a year of history on the first check
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def is_profile_trigger(form: str, items: str | None) -> bool:
    """Profile updates run on quarterly/annual reports and earnings releases (8-K item 2.02)."""
    return form in PERIODIC or (form == "8-K" and "2.02" in (items or "").split(","))


def parse_submissions(cik: int, sub: dict) -> list[dict]:
    recent = sub.get("filings", {}).get("recent", {})
    n = len(recent.get("accessionNumber", []))
    col = lambda k: recent.get(k) or [""] * n  # noqa: E731
    out = []
    for acc, form, items, accepted, filed, report, doc, xbrl in zip(
        col("accessionNumber"), col("form"), col("items"), col("acceptanceDateTime"),
        col("filingDate"), col("reportDate"), col("primaryDocument"), col("isXBRL"),
    ):
        if form not in FORMS or (form == "6-K" and not xbrl):
            continue
        if accepted:
            filed_at = datetime.fromisoformat(accepted.replace("Z", "+00:00")).astimezone(UTC).replace(tzinfo=None)
        else:
            filed_at = datetime.fromisoformat(filed)
        out.append({
            "accession": acc, "form": form, "items": items or None, "filed_at": filed_at,
            "period_end": date.fromisoformat(report) if report else None,
            "url": ARCHIVE_URL.format(cik=int(cik), acc=acc.replace("-", ""), doc=doc) if doc else
                   f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={int(cik)}",
        })
    return out


def record_filings(session: Session, ticker: str, parsed: list[dict], now: datetime | None = None) -> list[Filing]:
    """Store unseen filings. Returns the new ones that need a profile update (empty on the first, baseline check)."""
    now = now or _now()
    known = set(session.scalars(select(Filing.accession).where(Filing.ticker == ticker)))
    baseline = not known
    cutoff = now - timedelta(days=BASELINE_DAYS)
    queued: list[Filing] = []
    for p in parsed:
        # The window applies on every check: EDGAR lists years of filings and only recent ones can be new.
        if p["accession"] in known or p["filed_at"] < cutoff:
            continue
        trigger = not baseline and is_profile_trigger(p["form"], p["items"])
        f = Filing(ticker=ticker, processed_at=None if trigger else now, **p)
        session.add(f)
        known.add(p["accession"])
        if trigger:
            queued.append(f)
    session.flush()
    return queued


def check_filings(session: Session, edgar: EdgarClient, tickers: list[str] | None = None) -> dict[str, list[Filing]]:
    """Check every active stock (or the given ones). Returns {ticker: new queued filings} for those with any."""
    q = select(Universe.ticker, Universe.cik).where(Universe.active)
    if tickers:
        q = q.where(Universe.ticker.in_(tickers))
    out = {}
    for ticker, cik in session.execute(q).all():
        new = record_filings(session, ticker, parse_submissions(int(cik), edgar.submissions(int(cik))))
        if new:
            out[ticker] = new
    return out


def needs_new_figures(new: dict[str, list[Filing]]) -> list[str]:
    return sorted(t for t, fs in new.items() if any(f.form in PERIODIC for f in fs))
