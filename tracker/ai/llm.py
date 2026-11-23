"""The single wrapper for model calls (AGENTS.md rule 2). Nothing else imports the Anthropic SDK.

Each call: refuses when the month-to-date AI cost plus this call's worst case would pass MONTHLY_BUDGET_USD,
counts prompt tokens and refuses prompts over MAX_PROMPT_TOKENS (rule 5), calls the model with a pydantic
output schema (structured outputs), and logs tokens and cost to usage_log, including calls that fail after
the model ran.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tracker import config
from tracker.models import UsageLog

T = TypeVar("T", bound=BaseModel)
Task = Literal["routine", "profile"]

# USD per million tokens. Haiku 5.5 has a long-prompt tier: everything costs 5x above 100k prompt tokens.
PRICES: dict[str, dict[str, float]] = {
    "claude-haiku-5-5": {"in": 0.10, "out": 0.50, "cache_write": 0.125, "cache_read": 0.01},
    "claude-sonnet-5-5": {"in": 2.00, "out": 10.00, "cache_write": 2.50, "cache_read": 0.10},
}
LONG_PROMPT_TOKENS = {"claude-haiku-5-5": 100_000}
LONG_PROMPT_MULTIPLIER = 5.0
BATCH_DISCOUNT = 0.5


class LLMError(Exception):
    """A model call did not produce a usable result."""


class LLMUnavailable(LLMError):
    """No API key configured."""


class BudgetExceeded(LLMError):
    """The monthly AI budget would be passed (rule 6)."""


class PromptTooLarge(LLMError):
    """The prompt is over MAX_PROMPT_TOKENS (rule 5)."""


class LLMRefused(LLMError):
    """The model declined the request (stop_reason == "refusal")."""


@dataclass
class LLMResult(Generic[T]):
    output: T
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


def model_for(task: Task, model: str | None = None) -> tuple[str, str]:
    """(model, effort) for a task, from config. An explicit model (e.g. Haiku for a first profile) keeps the
    task's effort."""
    if model:
        return model, (config.EFFORT_PROFILE if task == "profile" else config.EFFORT_ROUTINE)
    if task == "profile":
        return config.MODEL_PROFILE, config.EFFORT_PROFILE
    return config.MODEL_ROUTINE, config.EFFORT_ROUTINE


def cost_usd(model: str, input_tokens: int, output_tokens: int, cache_write_tokens: int = 0,
             cache_read_tokens: int = 0, batch: bool = False) -> float:
    if model not in PRICES:
        raise LLMError(f"no price for model {model!r}; add it to tracker/ai/llm.py PRICES")
    p = PRICES[model]
    cost = (input_tokens * p["in"] + output_tokens * p["out"] + cache_write_tokens * p["cache_write"]
            + cache_read_tokens * p["cache_read"]) / 1_000_000
    prompt_tokens = input_tokens + cache_write_tokens + cache_read_tokens
    if prompt_tokens > LONG_PROMPT_TOKENS.get(model, float("inf")):
        cost *= LONG_PROMPT_MULTIPLIER
    return cost * (BATCH_DISCOUNT if batch else 1.0)


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def month_to_date_cost(session: Session, now: datetime | None = None) -> float:
    now = now or datetime.now(UTC).replace(tzinfo=None)
    q = select(func.coalesce(func.sum(UsageLog.cost_usd), 0)).where(UsageLog.created_at >= _month_start(now))
    return float(session.execute(q).scalar_one())


def budget_left(session: Session, now: datetime | None = None) -> float:
    return config.MONTHLY_BUDGET_USD - month_to_date_cost(session, now)


def log_usage(session: Session, job: str, model: str, input_tokens: int, output_tokens: int, cost: float,
              now: datetime | None = None) -> None:
    session.add(UsageLog(created_at=now or datetime.now(UTC).replace(tzinfo=None), job=job, model=model, input_tokens=input_tokens,
                         output_tokens=output_tokens, search_calls=0, cost_usd=round(cost, 6)))
    session.flush()


_client = None


def get_client():
    global _client
    if _client is None:
        if not config.ANTHROPIC_API_KEY:
            raise LLMUnavailable("ANTHROPIC_API_KEY is not set (.env locally, st.secrets / Actions secrets when deployed)")
        import anthropic

        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def call(session: Session, *, job: str, task: Task, system: str, user: str, output_model: type[T],
         max_tokens: int = 4000, client=None, now: datetime | None = None) -> LLMResult[T]:
    """Run one structured model call. Raises an LLMError subclass instead of returning a bad result."""
    client = client or get_client()
    model, effort = model_for(task)
    messages = [{"role": "user", "content": user}]

    spent = month_to_date_cost(session, now)
    if spent >= config.MONTHLY_BUDGET_USD:
        raise BudgetExceeded(f"month-to-date AI cost ${spent:.2f} has reached ${config.MONTHLY_BUDGET_USD:.2f}")

    prompt_tokens = client.messages.count_tokens(model=model, system=system, messages=messages,
                                                 output_format=output_model).input_tokens
    if prompt_tokens > config.MAX_PROMPT_TOKENS:
        raise PromptTooLarge(f"{prompt_tokens} prompt tokens > {config.MAX_PROMPT_TOKENS}; send filing sections, not whole filings")

    worst_case = cost_usd(model, prompt_tokens, max_tokens)
    if spent + worst_case > config.MONTHLY_BUDGET_USD:
        raise BudgetExceeded(f"this call (up to ${worst_case:.4f}) would pass the ${config.MONTHLY_BUDGET_USD:.2f} budget")

    resp = client.messages.parse(model=model, max_tokens=max_tokens, system=system, messages=messages,
                                 output_config={"effort": effort}, output_format=output_model)

    u = resp.usage
    cache_write = getattr(u, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
    cost = cost_usd(model, u.input_tokens, u.output_tokens, cache_write, cache_read)
    log_usage(session, job, model, u.input_tokens + cache_write + cache_read, u.output_tokens, cost, now)

    if resp.stop_reason == "refusal":
        raise LLMRefused(f"{model} declined ({getattr(resp, 'stop_details', None)})")
    if resp.stop_reason == "max_tokens":
        raise LLMError(f"{model} hit max_tokens={max_tokens} before finishing")
    if resp.parsed_output is None:
        raise LLMError(f"{model} returned no parsable output")
    return LLMResult(output=resp.parsed_output, model=model, input_tokens=u.input_tokens,
                     output_tokens=u.output_tokens, cost_usd=cost)



# ---- Message Batches (50% off; results within 24 hours, usually under 1) -------------------------------

@dataclass
class BatchRequest:
    custom_id: str          # ^[a-zA-Z0-9_-]{1,64}$
    system: str
    user: str
    model: str
    prompt_tokens: int = 0  # filled in by submit_batch


def _output_config(effort: str, output_model: type[BaseModel]) -> dict:
    from anthropic import transform_schema

    return {"effort": effort, "format": {"type": "json_schema", "schema": transform_schema(output_model.model_json_schema())}}


def submit_batch(session: Session, *, task: Task, requests: list[BatchRequest], output_model: type[T],
                 max_tokens: int = 4000, client=None, now: datetime | None = None) -> tuple[str | None, dict[str, str]]:
    """Count tokens, check the budget against the worst case at batch prices, and create one batch.
    Returns (batch id or None, {custom_id: reason} for requests left out)."""
    client = client or get_client()
    skipped: dict[str, str] = {}
    kept: list[BatchRequest] = []
    worst = 0.0
    for r in requests:
        r.prompt_tokens = client.messages.count_tokens(model=r.model, system=r.system,
                                                       messages=[{"role": "user", "content": r.user}],
                                                       output_format=output_model).input_tokens
        if r.prompt_tokens > config.MAX_PROMPT_TOKENS:
            skipped[r.custom_id] = f"{r.prompt_tokens} prompt tokens > {config.MAX_PROMPT_TOKENS}"
            continue
        kept.append(r)
        worst += cost_usd(r.model, r.prompt_tokens, max_tokens, batch=True)
    if not kept:
        return None, skipped
    spent = month_to_date_cost(session, now)
    if spent + worst > config.MONTHLY_BUDGET_USD:
        raise BudgetExceeded(f"batch of {len(kept)} (up to ${worst:.2f}) would pass the ${config.MONTHLY_BUDGET_USD:.2f} "
                             f"budget (${spent:.2f} spent)")
    batch = client.messages.batches.create(requests=[
        {"custom_id": r.custom_id,
         "params": {"model": r.model, "max_tokens": max_tokens, "system": r.system,
                    "messages": [{"role": "user", "content": r.user}],
                    "output_config": _output_config(model_for(task, r.model)[1], output_model)}}
        for r in kept])
    return batch.id, skipped


def batch_status(batch_id: str, client=None) -> tuple[str, dict]:
    b = (client or get_client()).messages.batches.retrieve(batch_id)
    return b.processing_status, b.request_counts.to_dict() if hasattr(b.request_counts, "to_dict") else dict(b.request_counts)


def collect_batch(session: Session, batch_id: str, *, job: str, output_model: type[T], max_tokens: int = 4000,
                  client=None, now: datetime | None = None) -> dict[str, LLMResult[T] | LLMError]:
    """Results of an ended batch: {custom_id: LLMResult or the LLMError explaining why it is unusable}.
    Logs usage at batch prices for every request the model ran (errored/expired requests are not billed)."""
    client = client or get_client()
    out: dict[str, LLMResult[T] | LLMError] = {}
    for r in client.messages.batches.results(batch_id):
        res = r.result
        if res.type != "succeeded":
            out[r.custom_id] = LLMError(f"batch request {res.type}" + (f": {res.error.error.type}" if res.type == "errored" else ""))
            continue
        msg = res.message
        u = msg.usage
        cache_write = getattr(u, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
        cost = cost_usd(msg.model, u.input_tokens, u.output_tokens, cache_write, cache_read, batch=True)
        log_usage(session, job, msg.model, u.input_tokens + cache_write + cache_read, u.output_tokens, cost, now)
        if msg.stop_reason == "refusal":
            out[r.custom_id] = LLMRefused(f"{msg.model} declined")
            continue
        if msg.stop_reason == "max_tokens":
            out[r.custom_id] = LLMError(f"{msg.model} hit max_tokens={max_tokens} before finishing")
            continue
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        try:
            parsed = output_model.model_validate_json(text)
        except Exception as e:  # pydantic ValidationError or bad JSON
            out[r.custom_id] = LLMError(f"unparsable output: {type(e).__name__}")
            continue
        out[r.custom_id] = LLMResult(output=parsed, model=msg.model, input_tokens=u.input_tokens,
                                     output_tokens=u.output_tokens, cost_usd=cost)
    return out
