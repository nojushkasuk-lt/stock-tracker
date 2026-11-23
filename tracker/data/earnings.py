"""Issuer-announced dates and links to the latest stored results filings."""

from datetime import date

from sqlalchemy import and_, func, or_, select

from tracker.data.universe import CONFIG_DIR, read_csv
from tracker.models import Filing


def announced_dates(today: date) -> dict[str, tuple[date, str]]:
    """The nearest upcoming issuer announcement for each ticker in the curated calendar."""
    dates = {}
    for row in sorted(read_csv(CONFIG_DIR / "earnings.csv"), key=lambda row: row["date"]):
        day = date.fromisoformat(row["date"])
        if day >= today:
            dates.setdefault(row["ticker"], (day, row["source"]))
    return dates


def latest_reports(session, tickers: list[str]) -> dict[str, Filing]:
    """Latest earnings releases or periodic reports. Generic 8-K and 6-K filings do not qualify."""
    rank = func.row_number().over(
        partition_by=Filing.ticker, order_by=(Filing.filed_at.desc(), Filing.accession.desc())
    )
    reports = select(Filing.accession, rank.label("position")).where(
        Filing.ticker.in_(tickers),
        or_(
            Filing.form.in_(("10-K", "10-Q", "20-F")),
            and_(Filing.form == "8-K", Filing.items.like("%2.02%")),
        ),
    ).subquery()
    latest = session.scalars(select(Filing).join(reports, Filing.accession == reports.c.accession).where(reports.c.position == 1))
    return {filing.ticker: filing for filing in latest}
