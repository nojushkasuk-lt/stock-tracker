"""Filing-triggered company profiles, written by the profile model (Sonnet).

This module holds the prompt, the output schema and validation. Generation from the filings queue comes next.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from tracker.ai import prompts
from tracker.ai.citations import Checked, Claim, Source, Validator, render_sources

SECTIONS = ("overview", "strategy_and_trajectory", "bull_case", "bear_case")


class ProfileOut(BaseModel):
    overview: list[Claim] = Field(default_factory=list)
    strategy_and_trajectory: list[Claim] = Field(default_factory=list)
    bull_case: list[Claim] = Field(default_factory=list)
    bear_case: list[Claim] = Field(default_factory=list)
    what_changed: str = ""


def system_prompt() -> str:
    return prompts.load("profile").replace("{rules}", prompts.load("rules"))


def user_prompt(company: str, ticker: str, filing: str, sources: list[Source]) -> str:
    return f"Company: {company} ({ticker}). New filing: {filing}.\n\nSources:\n{render_sources(sources)}"


def validate(out: ProfileOut, sources: list[Source]) -> tuple[ProfileOut | None, Checked]:
    """Drop bad claims. None if a section ends up empty (the old profile stays in place)."""
    v = Validator(sources)
    kept = {name: v.claims(name, getattr(out, name)) for name in SECTIONS}
    what_changed = v.free_text("what_changed", out.what_changed, firm_allowed=True) or ""
    if any(not claims for claims in kept.values()):
        return None, v.checked
    return ProfileOut(**kept, what_changed=what_changed), v.checked
