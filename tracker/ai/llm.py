"""The single wrapper for model calls (AGENTS.md rule 2). Nothing else imports the Anthropic SDK.

Each call: refuses when the month-to-date AI cost plus this call's worst case would pass MONTHLY_BUDGET_USD,
counts prompt tokens and refuses prompts over MAX_PROMPT_TOKENS (rule 5), calls the model with a pydantic
output schema (structured outputs), and logs tokens and cost to usage_log, including calls that fail after
the model ran.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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


def model_for(task: Task) -> tuple[str, str]:
    """(model, effort) for a task, from config."""
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
    now = now or datetime.now()
    q = select(func.coalesce(func.sum(UsageLog.cost_usd), 0)).where(UsageLog.created_at >= _month_start(now))
    return float(session.execute(q).scalar_one())


def budget_left(session: Session, now: datetime | None = None) -> float:
    return config.MONTHLY_BUDGET_USD - month_to_date_cost(session, now)


def log_usage(session: Session, job: str, model: str, input_tokens: int, output_tokens: int, cost: float,
              now: datetime | None = None) -> None:
    session.add(UsageLog(created_at=now or datetime.now(), job=job, model=model, input_tokens=input_tokens,
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
