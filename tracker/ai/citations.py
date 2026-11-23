"""Sources in, cited claims out (AGENTS.md rules 3, 4 and 11).

Every input the model sees is a Source with an ID. Model output is validated here before anything is stored:
- a claim citing an ID that was not in the input (or citing nothing) is dropped;
- a claim backed only by headlines must use cautious wording and must not state a cause as fact;
- every number in the output must appear in the input (numbers never come from the model);
- "beat" / "miss" only when the input itself says what was expected.
Only id, url and outlet of the cited sources are kept for storage; headlines are never stored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

SourceKind = Literal["headline", "primary", "metrics", "own"]
# headline: a news result seen as a headline only. primary: an SEC filing / earnings release read in full.
# metrics: our own numbers computed from EDGAR or the price provider. own: our previous profile or note.

NO_CATALYST = "No clear catalyst found yet."


class Source(BaseModel):
    id: str
    kind: SourceKind
    text: str                 # what the model is shown (headline, filing excerpt, metrics line)
    outlet: str | None = None
    url: str | None = None
    date: str | None = None
    label: str | None = None  # e.g. "8-K item 2.02", "10-K Item 7 MD&A"

    def stored(self) -> dict:
        """What ai_outputs.sources may keep: no headline or filing text."""
        return {"id": self.id, "url": self.url, "outlet": self.outlet}


class Claim(BaseModel):
    text: str
    source_ids: list[str] = Field(default_factory=list)


def render_sources(sources: list[Source]) -> str:
    lines = []
    for s in sources:
        meta = [f"kind={s.kind}"]
        if s.outlet:
            meta.append(f"outlet={s.outlet}")
        if s.date:
            meta.append(f"date={s.date}")
        if s.label:
            meta.append(f"label={s.label}")
        lines.append(f"[{s.id}] {' '.join(meta)}\n{s.text}")
    return "\n\n".join(lines)


# ---- wording checks -----------------------------------------------------------------------------

HEDGES = re.compile(
    r"\b(coverage|reports?|reported|reportedly|suggests?|points? to|appears?|may|might|could|possibly|"
    r"according to|headlines?|some investors|analysts? (?:say|said|think)|not confirmed)\b", re.I)
FIRM_CAUSE = re.compile(
    r"\b(because|due to|caused by|driven by|as a result of|thanks to|on the back of|sent shares|led to|"
    r"triggered|the reason)\b", re.I)
BEAT_MISS = re.compile(r"\b(beat|beats|beating|missed|misses|miss|topped|fell short of)\b", re.I)
EXPECTATION = re.compile(r"\b(estimates?|expectations?|consensus|forecasts?|expected|guidance of)\b", re.I)
NUMBER = re.compile(r"(?<![\w.])[-+]?\$?\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    out = set()
    for raw in NUMBER.findall(text):
        n = raw.lstrip("+-$").replace(",", "")
        if "." in n:
            n = n.rstrip("0").rstrip(".")
        out.add(n)
    return out


def unsupported_numbers(text: str, allowed: set[str]) -> set[str]:
    """Numbers in text that appear nowhere in the input. Single digits are allowed (counts, 'two quarters')."""
    return {n for n in _numbers(text) if n not in allowed and not (n.isdigit() and len(n) == 1)}


def is_hedged(text: str) -> bool:
    return bool(HEDGES.search(text))


def wording_problem(text: str, cited: list[Source], input_text: str) -> str | None:
    """Why a claim's wording is not allowed for the sources it cites, or None."""
    if BEAT_MISS.search(text) and not EXPECTATION.search(input_text):
        return "says beat/miss but the input gives no expectation"
    if any(s.kind == "primary" for s in cited):
        return None
    if all(s.kind in ("metrics", "own") for s in cited):
        return None  # our own numbers and earlier text: facts, but no causes
    if not is_hedged(text):
        return "headline-only claim without cautious wording"
    cause = FIRM_CAUSE.search(text)
    if cause and not HEDGES.search(text[:cause.start()]):  # the hedge must come before the cause
        return "headline-only claim states a cause as fact"
    return None


# ---- validation ---------------------------------------------------------------------------------

@dataclass
class Dropped:
    where: str
    text: str
    reason: str


@dataclass
class Checked:
    """Result of validating one model output. `dropped` lists everything removed and why."""
    dropped: list[Dropped] = field(default_factory=list)
    cited_ids: set[str] = field(default_factory=set)

    def stored_sources(self, sources: list[Source]) -> list[dict]:
        return [s.stored() for s in sources if s.id in self.cited_ids]


class Validator:
    def __init__(self, sources: list[Source], extra_input: str = ""):
        self.by_id = {s.id: s for s in sources}
        self.input_text = extra_input + "\n" + "\n".join(s.text for s in sources)
        self.allowed_numbers = _numbers(self.input_text)
        self.checked = Checked()

    def claims(self, where: str, claims: list[Claim]) -> list[Claim]:
        kept = []
        for c in claims:
            reason = self._claim_problem(c)
            if reason:
                self.checked.dropped.append(Dropped(where, c.text, reason))
                continue
            kept.append(c)
            self.checked.cited_ids.update(c.source_ids)
        return kept

    def _claim_problem(self, c: Claim) -> str | None:
        if not c.source_ids:
            return "cites no source"
        unknown = [i for i in c.source_ids if i not in self.by_id]
        if unknown:
            return f"cites unknown source IDs {unknown}"
        bad = unsupported_numbers(c.text, self.allowed_numbers)
        if bad:
            return f"numbers not in the input: {sorted(bad)}"
        return wording_problem(c.text, [self.by_id[i] for i in c.source_ids], self.input_text)

    def free_text(self, where: str, text: str, firm_allowed: bool) -> str | None:
        """Check uncited text (a summary). Returns the text, or None if it must not be shown."""
        bad = unsupported_numbers(text, self.allowed_numbers)
        reason = f"numbers not in the input: {sorted(bad)}" if bad else None
        if not reason and BEAT_MISS.search(text) and not EXPECTATION.search(self.input_text):
            reason = "says beat/miss but the input gives no expectation"
        if not reason and not firm_allowed and FIRM_CAUSE.search(text) and not is_hedged(text):
            reason = "states a cause as fact without a primary source"
        if reason:
            self.checked.dropped.append(Dropped(where, text, reason))
            return None
        return text

    def ranked(self, ids: list[str], allowed_kinds: tuple[str, ...] = ("headline", "primary")) -> list[str]:
        seen, out = set(), []
        for i in ids:
            if i in self.by_id and i not in seen and self.by_id[i].kind in allowed_kinds:
                seen.add(i)
                out.append(i)
        return out
