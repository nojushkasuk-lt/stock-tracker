"""Move notes (market / industry / stock) and link ranking, written by the routine model (Haiku).

This module holds the prompt, the output schema and validation. Generation and caching come next.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from tracker.ai import prompts
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


def validate(out: MoveNoteOut, m: MoveInput, sources: list[Source]) -> tuple[MoveNoteOut, Checked]:
    """Drop bad claims. If the summary breaks a rule it is replaced by the first valid claim (or the
    no-catalyst line), so a rule-breaking sentence is never shown."""
    v = Validator(sources, extra_input=facts_line(m))
    claims = v.claims("claims", out.claims)
    primary_cited = any(v.by_id[i].kind == "primary" for c in claims for i in c.source_ids)
    summary = v.free_text("summary", out.summary, firm_allowed=primary_cited)
    if summary is None:
        summary = claims[0].text if claims else NO_CATALYST
    ranked = v.ranked(out.ranked_source_ids)
    confidence = out.confidence
    if confidence == "high" and not primary_cited:
        confidence = "medium"  # high is reserved for moves a primary source explains
    if not claims:
        confidence = "low"
    return MoveNoteOut(summary=summary, claims=claims, confidence=confidence, ranked_source_ids=ranked), v.checked
