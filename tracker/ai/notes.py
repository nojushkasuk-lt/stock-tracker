"""Move notes (market / industry / stock) and link ranking, written by the routine model (Haiku).

Notes are shared: one per stock, industry or market per day (scope decided by analysis/moves.py). The model
also ranks the links; the ranked links are stored (id, url, outlet only) so the page can show them later.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from sqlalchemy.orm import Session

from tracker.ai import outputs, prompts
from tracker.ai.citations import NO_CATALYST, Checked, Claim, Source, Validator, render_sources

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
        client=client, now=now)
