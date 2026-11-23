"""tracker/ai/llm.py: budget stop, prompt-size cap, cost log, refusals. No real API calls."""

from datetime import datetime
from types import SimpleNamespace

import pytest
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker import config
from tracker.ai import llm
from tracker.db import create_tables, make_engine
from tracker.models import UsageLog

NOW = datetime(2026, 11, 23, 12, 0)


class Note(BaseModel):
    summary: str


class FakeMessages:
    def __init__(self, prompt_tokens=1_000, in_tok=1_000, out_tok=200, stop="end_turn", parsed=Note(summary="ok")):
        self.prompt_tokens, self.in_tok, self.out_tok, self.stop, self.parsed = prompt_tokens, in_tok, out_tok, stop, parsed
        self.parse_calls = []

    def count_tokens(self, **kw):
        return SimpleNamespace(input_tokens=self.prompt_tokens)

    def parse(self, **kw):
        self.parse_calls.append(kw)
        usage = SimpleNamespace(input_tokens=self.in_tok, output_tokens=self.out_tok,
                                cache_creation_input_tokens=0, cache_read_input_tokens=0)
        return SimpleNamespace(usage=usage, stop_reason=self.stop, parsed_output=self.parsed, stop_details=None)


def fake(**kw):
    return SimpleNamespace(messages=FakeMessages(**kw))


@pytest.fixture
def db(tmp_path):
    e = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    create_tables(e)
    with Session(e) as s:
        yield s


def run(db, client, task="routine"):
    return llm.call(db, job="daily", task=task, system="sys", user="u", output_model=Note, client=client, now=NOW)


def spend(db, usd, when=NOW):
    db.add(UsageLog(created_at=when, job="daily", model="claude-haiku-5-5", cost_usd=usd))
    db.flush()


def test_cost_matches_published_prices():
    assert llm.cost_usd("claude-haiku-5-5", 10_000, 1_000_000) == pytest.approx(0.001 + 0.50)
    assert llm.cost_usd("claude-sonnet-5-5", 1_000_000, 1_000_000) == pytest.approx(12.00)
    assert llm.cost_usd("claude-sonnet-5-5", 1_000_000, 0, batch=True) == pytest.approx(1.00)


def test_haiku_costs_five_times_more_above_100k_prompt_tokens():
    small = llm.cost_usd("claude-haiku-5-5", 100_000, 1_000)
    big = llm.cost_usd("claude-haiku-5-5", 100_001, 1_000)
    assert big / small == pytest.approx(5.0, rel=1e-3)


def test_unknown_model_has_no_price():
    with pytest.raises(llm.LLMError):
        llm.cost_usd("some-other-model", 1, 1)


def test_models_and_effort_come_from_config(db, monkeypatch):
    monkeypatch.setattr(config, "MODEL_PROFILE", "claude-sonnet-5-5")
    monkeypatch.setattr(config, "MODEL_ROUTINE", "claude-haiku-5-5")
    c = fake()
    assert run(db, c, task="profile").model == "claude-sonnet-5-5"
    assert run(db, c, task="routine").model == "claude-haiku-5-5"
    assert c.messages.parse_calls[0]["output_config"] == {"effort": config.EFFORT_PROFILE}
    assert c.messages.parse_calls[0]["output_format"] is Note


def test_successful_call_logs_tokens_and_cost(db):
    r = run(db, fake(in_tok=2_000, out_tok=300))
    assert r.output.summary == "ok"
    row = db.execute(select(UsageLog)).scalar_one()
    assert (row.job, row.model, row.input_tokens, row.output_tokens) == ("daily", "claude-haiku-5-5", 2_000, 300)
    assert row.cost_usd == pytest.approx(llm.cost_usd("claude-haiku-5-5", 2_000, 300), abs=1e-6)


def test_budget_reached_stops_before_any_api_call(db, monkeypatch):
    monkeypatch.setattr(config, "MONTHLY_BUDGET_USD", 8.0)
    spend(db, 8.0)
    c = fake()
    with pytest.raises(llm.BudgetExceeded):
        run(db, c)
    assert c.messages.parse_calls == []


def test_call_whose_worst_case_would_pass_the_budget_is_refused(db, monkeypatch):
    monkeypatch.setattr(config, "MONTHLY_BUDGET_USD", 8.0)
    spend(db, 7.999)
    c = fake(prompt_tokens=50_000)  # worst case on Sonnet: 50k in + 4k out = $0.14
    with pytest.raises(llm.BudgetExceeded):
        run(db, c, task="profile")
    assert c.messages.parse_calls == []


def test_last_month_spend_does_not_count(db, monkeypatch):
    monkeypatch.setattr(config, "MONTHLY_BUDGET_USD", 8.0)
    spend(db, 50.0, when=datetime(2026, 10, 31, 23, 59))
    assert llm.month_to_date_cost(db, NOW) == 0
    run(db, fake())


def test_searches_in_usage_log_cost_nothing(db):
    db.add(UsageLog(created_at=NOW, job="coverage", model=None, search_calls=1, cost_usd=0.0))
    db.flush()
    assert llm.month_to_date_cost(db, NOW) == 0


def test_prompt_over_100k_tokens_is_refused(db):
    c = fake(prompt_tokens=100_001)
    with pytest.raises(llm.PromptTooLarge):
        run(db, c)
    assert c.messages.parse_calls == []
    assert db.execute(select(UsageLog)).first() is None


def test_refusal_is_raised_but_still_logged(db):
    with pytest.raises(llm.LLMRefused):
        run(db, fake(stop="refusal", parsed=None))
    assert db.execute(select(UsageLog)).scalar_one().cost_usd > 0


def test_truncated_output_is_an_error(db):
    with pytest.raises(llm.LLMError):
        run(db, fake(stop="max_tokens", parsed=None))


def test_missing_api_key_raises_clearly(monkeypatch):
    monkeypatch.setattr(llm, "_client", None)
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    with pytest.raises(llm.LLMUnavailable):
        llm.get_client()


def test_nothing_else_imports_the_anthropic_sdk():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    files = list(root.glob("tracker/**/*.py")) + list(root.glob("jobs/*.py")) + list(root.glob("ui/*.py")) + [root / "app.py"]
    offenders = [str(f.relative_to(root)) for f in files
                 if f.name != "llm.py" and ("import anthropic" in f.read_text() or "from anthropic" in f.read_text())]
    assert offenders == []
