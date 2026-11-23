"""Move notes (market / industry / stock) and link ranking, written by the routine model (Haiku).

Notes are shared: one per stock, industry or market per day (scope decided by analysis/moves.py). The model
also ranks the links; the ranked links are stored (id, url, outlet only) so the page can show them later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker import config
from tracker.ai import llm, outputs, prompts
from tracker.ai.citations import NO_CATALYST, Checked, Claim, Source, Validator, render_sources
from tracker.analysis import moves
from tracker.data import news
from tracker.data.filing_text import cap
from tracker.models import AiOutput, Filing, Move, Universe

Scope = Literal["market", "industry", "stock"]


class MoveNoteOut(BaseModel):
    """What the model must return (structured output schema)."""
    summary: str
    claims: list[Claim] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"]
    ranked_source_ids: list[str] = Field(default_factory=list)


class MoveInput(BaseModel):
    subject: str               # "ADBE (Adobe)", "Software industry", "S&P 500"
    scope: Scope
    return_pct: float
    market_return_pct: float | None = None
    industry_return_pct: float | None = None
    industry: str | None = None
    date: str


def system_prompt() -> str:
    return prompts.load("move_note").replace("{rules}", prompts.load("rules"))


def facts_line(m: MoveInput) -> str:
    parts = [f"Subject: {m.subject}. Scope: {m.scope}. Date: {m.date}. Move: {m.return_pct:+.1f}%."]
    if m.market_return_pct is not None:
        parts.append(f"S&P 500 (SPY): {m.market_return_pct:+.1f}%.")
    if m.industry_return_pct is not None:
        parts.append(f"{m.industry or 'Industry'} peers average: {m.industry_return_pct:+.1f}%.")
    return " ".join(parts)


def user_prompt(m: MoveInput, sources: list[Source]) -> str:
    body = render_sources(sources) if sources else "(no sources found)"
    return f"{facts_line(m)}\n\nSources:\n{body}"


SUMMARY_MAX_WORDS = 60


def trim_summary(text: str, max_words: int = SUMMARY_MAX_WORDS) -> str:
    """Keep whole sentences up to max_words (always at least the first sentence)."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    out, words = [], 0
    for s in sentences:
        n = len(s.split())
        if out and words + n > max_words:
            break
        out.append(s)
        words += n
    return " ".join(out)


def validate(out: MoveNoteOut, m: MoveInput, sources: list[Source]) -> tuple[MoveNoteOut, Checked]:
    """Drop bad claims. If the summary breaks a rule it is replaced by the first valid claim (or the
    no-catalyst line), so a rule-breaking sentence is never shown."""
    v = Validator(sources, extra_input=facts_line(m))
    claims = v.claims("claims", out.claims)
    primary_cited = any(v.by_id[i].kind == "primary" for c in claims for i in c.source_ids)
    summary = v.free_text("summary", out.summary, firm_allowed=primary_cited)
    if summary is None:
        summary = claims[0].text if claims else NO_CATALYST
    summary = trim_summary(summary)
    ranked = v.ranked(out.ranked_source_ids)
    v.checked.cited_ids.update(ranked)  # ranked links are shown too, so their url / outlet are kept
    confidence = out.confidence
    if confidence == "high" and not primary_cited:
        confidence = "medium"  # high is reserved for moves a primary source explains
    if not claims:
        confidence = "low"
    return MoveNoteOut(summary=summary, claims=claims, confidence=confidence, ranked_source_ids=ranked), v.checked


KIND_BY_SCOPE = {"stock": "stock_note", "industry": "industry_note", "market": "market_note"}


def sources_from_links(links, start: int = 1) -> list[Source]:
    """News links (tracker.data.news.NewsLink) -> headline sources N1, N2, ... Headlines go to the model only."""
    return [Source(id=f"N{i}", kind="headline", text=l.title, outlet=l.outlet, url=l.url,
                   date=l.published.date().isoformat() if l.published else None)
            for i, l in enumerate(links, start)]


def scope_key(m: MoveInput, ticker: str | None = None) -> str:
    if m.scope == "market":
        return "market"
    if m.scope == "industry":
        return f"industry:{m.industry}"
    if not ticker:
        raise ValueError("a stock note needs a ticker")
    return ticker


def write_note(session: Session, m: MoveInput, sources: list[Source], *, ticker: str | None = None,
               job: str = "daily", client=None, now: datetime | None = None):
    """Generate (or reuse) the note for this move. Returns the ai_outputs row, or None if rejected."""
    return outputs.generate(
        session, kind=KIND_BY_SCOPE[m.scope], scope_key=scope_key(m, ticker), job=job, task="routine",
        system=system_prompt(), user=user_prompt(m, sources), output_model=MoveNoteOut, sources=sources,
        validate=lambda out: validate(out, m, sources), confidence=lambda out: out.confidence,
        extra={"date": m.date, "subject": m.subject, "return_pct": m.return_pct,
               "market_return_pct": m.market_return_pct, "industry_return_pct": m.industry_return_pct},
        client=client, now=now)


# ---- explaining a day's moves (called by jobs/daily.py) ---------------------------------------------

def _close_utc(day: date) -> datetime:
    """4 pm New York time on `day`, as naive UTC (filings.filed_at is stored that way)."""
    return datetime.combine(day, time(16), ZoneInfo("America/New_York")).astimezone(UTC).replace(tzinfo=None)


def earnings_source(session: Session, fetcher, ticker: str, day: date) -> Source | None:
    """The earnings release (8-K item 2.02) filed in the three days up to that day's close, if any."""
    f = session.scalars(select(Filing).where(
        Filing.ticker == ticker, Filing.form == "8-K", Filing.items.like("%2.02%"),
        Filing.filed_at >= _close_utc(day) - timedelta(days=3), Filing.filed_at <= _close_utc(day))
        .order_by(Filing.filed_at.desc())).first()
    if f is None:
        return None
    sections = fetcher.sections(f.form, f.items, f.url)
    if not sections:
        return None
    sec = sections[0]
    return Source(id="F1", kind="primary", text=cap(sec.text, EARNINGS_CHARS), label=sec.label, url=sec.url,
                  outlet="SEC EDGAR", date=f.filed_at.date().isoformat())


EARNINGS_CHARS = 20_000  # about 5k tokens: the headline numbers and outlook are near the top of a release


def _note_for_day(session: Session, kind: str, key: str, day: date) -> AiOutput | None:
    row = outputs.latest(session, kind, key)
    return row if row is not None and row.content.get("date") == day.isoformat() else None


def _status(note: AiOutput | None, rechecked: bool) -> str:
    if note is None:
        return "pending"
    if note.content.get("claims"):
        return "explained"
    return "no_catalyst" if rechecked else "recheck"


@dataclass
class DayReport:
    notes: dict[str, str] = field(default_factory=dict)  # scope key -> outcome
    stopped: str | None = None


def explain_day(session: Session, d, brave, fetcher, *, client=None, now: datetime | None = None,
                only_pending: bool = False) -> DayReport:
    """Write the notes a classified day needs (analysis.moves.Day) and link each move to its note.

    One market note when the market alert is on or a stock moved with the market (refreshed at most every
    MARKET_NOTE_MIN_INTERVAL_HOURS), one note per industry, one per stock. Each needs one search. Moves with
    no catalyst are rechecked once after RECHECK_AFTER_HOURS (only_pending=True: rechecks only).
    """
    now = now or datetime.now()
    report = DayReport()
    by_ticker = {m.ticker: m for m in session.scalars(select(Move).where(Move.date == d.date))}
    names = dict(session.execute(select(Universe.ticker, Universe.name)).all())
    ds = d.date.isoformat()

    def todo(c) -> bool:
        m = by_ticker[c.ticker]
        if only_pending:
            return m.status == "recheck" and m.recheck_after is not None and m.recheck_after <= now
        return m.status in ("pending",)

    def link(tickers, note):
        for t in tickers:
            m = by_ticker[t]
            rechecked = m.status == "recheck"
            m.note_id = note.id if note is not None else m.note_id
            m.status = _status(note, rechecked)
            m.recheck_after = now + timedelta(hours=config.RECHECK_AFTER_HOURS) if m.status == "recheck" else None

    def search(q):
        return news.coverage_links(news.cached_search(session, brave, q, freshness=news.day_window(d.date),
                                                      job="daily"), news.load_outlets())

    groups: dict[tuple[str, str], list] = {}
    for c in d.moves:
        if todo(c):
            key = ("market", "market") if c.scope == "market" else \
                  ("industry", c.industry) if c.scope == "industry" else ("stock", c.ticker)
            groups.setdefault(key, []).append(c)
    if d.level != "none" and not only_pending:
        groups.setdefault(("market", "market"), [])

    try:
        for (scope, key), cs in groups.items():
            tickers = [c.ticker for c in cs]
            if scope == "market":
                note = _note_for_day(session, "market_note", "market", d.date)
                fresh = note is not None and note.created_at > now - timedelta(hours=config.MARKET_NOTE_MIN_INTERVAL_HOURS)
                if not fresh:
                    m = MoveInput(subject="S&P 500", scope="market", return_pct=d.index_return_pct, date=ds)
                    note = write_note(session, m, sources_from_links(search(news.market_query())), client=client, now=now) or note
                report.notes["market"] = "reused" if fresh else ("written" if note else "rejected")
            elif scope == "industry":
                movers = sorted(cs, key=lambda c: -abs(c.return_pct))
                avg = moves.industry_average(key, d.returns, d.industries)
                m = MoveInput(subject=f"{key} industry", scope="industry", return_pct=avg, industry=key,
                              market_return_pct=d.index_return_pct, date=ds)
                links = search(news.industry_query([names.get(c.ticker, c.ticker) for c in movers]))
                note = write_note(session, m, sources_from_links(links), client=client, now=now)
                report.notes[f"industry:{key}"] = "written" if note else "rejected"
            else:
                c = cs[0]
                m = MoveInput(subject=f"{c.ticker} ({names.get(c.ticker, c.ticker)})", scope="stock",
                              return_pct=c.return_pct, market_return_pct=d.index_return_pct,
                              industry_return_pct=c.industry_return_pct, industry=c.industry, date=ds)
                primary = earnings_source(session, fetcher, c.ticker, d.date)
                links = search(news.coverage_query(names.get(c.ticker, c.ticker), c.ticker))
                sources = ([primary] if primary else []) + sources_from_links(links)
                note = write_note(session, m, sources, ticker=c.ticker, client=client, now=now)
                report.notes[c.ticker] = "written" if note else "rejected"
            link(tickers, note)
    except (llm.BudgetExceeded, llm.LLMUnavailable, news.SearchCapReached, news.NewsNotConfigured) as e:
        report.stopped = f"{type(e).__name__}: {e}"
    session.flush()
    return report
