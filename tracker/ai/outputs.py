"""Store and reuse AI results (ai_outputs). Same model + prompt -> same input_hash -> no new call.

`generate` is the one path from inputs to a stored result: cache lookup, model call (llm.py), validation
(citations.py), then save. Only validated content is saved, plus id / url / outlet of the cited sources.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Callable

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker.ai import llm
from tracker.ai.citations import Checked, Source
from tracker.models import AiOutput

PROMPT_VERSION = "1"  # bump to force regeneration after a prompt or schema change


def input_hash(model: str, system: str, user: str, schema: type[BaseModel]) -> str:
    blob = json.dumps([PROMPT_VERSION, model, system, user, schema.__name__], ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def find(session: Session, kind: str, scope_key: str, h: str) -> AiOutput | None:
    return session.scalars(select(AiOutput).where(AiOutput.kind == kind, AiOutput.scope_key == scope_key,
                                                  AiOutput.input_hash == h)).first()


def latest(session: Session, kind: str, scope_key: str) -> AiOutput | None:
    return session.scalars(select(AiOutput).where(AiOutput.kind == kind, AiOutput.scope_key == scope_key)
                           .order_by(AiOutput.created_at.desc(), AiOutput.id.desc())).first()


def generate[T: BaseModel](
    session: Session, *, kind: str, scope_key: str, job: str, task: llm.Task, system: str, user: str,
    output_model: type[T], sources: list[Source], validate: Callable[[T], tuple[T | None, Checked]],
    confidence: Callable[[T], str | None] = lambda _: None, valid_until: datetime | None = None,
    max_tokens: int = 4000,
    client=None, now: datetime | None = None,
) -> AiOutput | None:
    """Cached result for these exact inputs, or a new validated one. None when validation rejects the output
    (nothing is stored, so the next run tries again). LLM errors (budget, refusal, ...) propagate."""
    model, _ = llm.model_for(task)
    h = input_hash(model, system, user, output_model)
    hit = find(session, kind, scope_key, h)
    if hit is not None:
        return hit
    result = llm.call(session, job=job, task=task, system=system, user=user, output_model=output_model,
                      max_tokens=max_tokens, client=client, now=now)
    out, checked = validate(result.output)
    if out is None:
        return None
    content = out.model_dump()
    content["dropped"] = [{"where": d.where, "text": d.text, "reason": d.reason} for d in checked.dropped]
    row = AiOutput(kind=kind, scope_key=scope_key, model=result.model, input_hash=h, content=content,
                   sources=checked.stored_sources(sources), confidence=confidence(out),
                   created_at=now or datetime.now(), valid_until=valid_until)
    session.add(row)
    session.flush()
    return row
