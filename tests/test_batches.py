"""First profiles through the Batch API: model by rank, budget check at batch prices, collection with validation."""

from datetime import datetime
from types import SimpleNamespace

import pytest

from test_llm import NOW, db  # noqa: F401
from test_profiles import FakeFetcher, GOOD, ProfileOut, queue
from tracker import config
from tracker.ai import llm, profiles
from tracker.models import AiBatch, AiOutput, Filing, Universe


class FakeBatches:
    def __init__(self, parent):
        self.parent, self.created = parent, None

    def create(self, requests):
        self.created = requests
        return SimpleNamespace(id="msgbatch_test")

    def retrieve(self, batch_id):
        return SimpleNamespace(processing_status=self.parent.status, request_counts={"succeeded": len(self.created or [])})

    def results(self, batch_id):
        for r in self.created:
            text = self.parent.outputs.get(r["custom_id"], GOOD.model_dump_json())
            msg = SimpleNamespace(model=r["params"]["model"], stop_reason="end_turn",
                                  usage=SimpleNamespace(input_tokens=30_000, output_tokens=4_000,
                                                        cache_creation_input_tokens=0, cache_read_input_tokens=0),
                                  content=[SimpleNamespace(type="text", text=text)])
            yield SimpleNamespace(custom_id=r["custom_id"], result=SimpleNamespace(type="succeeded", message=msg))


class FakeClient:
    def __init__(self, prompt_tokens=30_000):
        self.status, self.outputs = "ended", {}
        self.messages = SimpleNamespace(count_tokens=lambda **kw: SimpleNamespace(input_tokens=prompt_tokens),
                                        batches=FakeBatches(self))


def _universe(db, n=4):
    for i in range(1, n + 1):
        t = f"S{i:02d}"
        db.add(Universe(ticker=t, cik=str(i), name=f"Co {i}", industry="Retail", market_cap_rank=i, is_demo=False,
                        active=True, updated_at=NOW))
        db.flush()
        queue(db, t, f"acc{i}", form="10-K", filed=datetime(2026, 10, 1))
    db.flush()


def test_top_ranks_get_sonnet_the_rest_haiku_and_results_are_validated(db):
    _universe(db)
    c = FakeClient()
    c.outputs["S04"] = ProfileOut(about=GOOD.about).model_dump_json()  # missing required sections -> rejected
    bid = profiles.submit_first_profiles(db, FakeFetcher(), sonnet_top=2, client=c, now=NOW, log=lambda *_: None)
    assert bid == "msgbatch_test"
    models = {r["custom_id"]: r["params"]["model"] for r in c.messages.batches.created}
    assert models == {"S01": config.MODEL_PROFILE, "S02": config.MODEL_PROFILE, "S03": config.MODEL_ROUTINE, "S04": config.MODEL_ROUTINE}
    fmt = c.messages.batches.created[0]["params"]["output_config"]["format"]
    assert fmt["type"] == "json_schema" and "about" in fmt["schema"]["properties"]

    out = profiles.collect_profiles(db, bid, client=c, now=NOW, log=lambda *_: None)
    assert out["S04"].startswith("rejected") and all(out[t].startswith("saved") for t in ("S01", "S02", "S03"))
    rows = {r.scope_key: r for r in db.query(AiOutput).filter(AiOutput.kind == "profile")}
    assert rows["S01"].model == config.MODEL_PROFILE and rows["S03"].model == config.MODEL_ROUTINE
    assert db.get(Filing, "acc1").processed_at == NOW
    b = db.get(AiBatch, bid)
    assert b.collected_at == NOW and "sources" not in b.items["S01"]  # filing text not kept after collection
    assert profiles.collect_profiles(db, bid, client=c, now=NOW) == {}  # collected once


def test_batch_cost_is_half_price_and_checked_against_the_budget(db, monkeypatch):
    assert llm.cost_usd("claude-sonnet-5-5", 1_000_000, 0, batch=True) == pytest.approx(1.0)
    assert llm.cost_usd("claude-haiku-5-5", 50_000, 10_000, batch=True) == pytest.approx(0.005)  # $0.05 / $0.25 per MTok
    _universe(db)
    monkeypatch.setattr(config, "MONTHLY_BUDGET_USD", 0.05)
    with pytest.raises(llm.BudgetExceeded):
        profiles.submit_first_profiles(db, FakeFetcher(), sonnet_top=4, client=FakeClient(), now=NOW, log=lambda *_: None)
    assert db.query(AiBatch).count() == 0


def test_prompts_over_the_cap_are_left_out(db):
    _universe(db, 1)
    c = FakeClient(prompt_tokens=config.MAX_PROMPT_TOKENS + 1)
    assert profiles.submit_first_profiles(db, FakeFetcher(), client=c, now=NOW, log=lambda *_: None) is None


def test_unfinished_batches_are_not_collected(db):
    _universe(db, 1)
    c = FakeClient()
    bid = profiles.submit_first_profiles(db, FakeFetcher(), client=c, now=NOW, log=lambda *_: None)
    c.status = "in_progress"
    assert profiles.collect_profiles(db, bid, client=c, now=NOW, log=lambda *_: None) == {}
    assert db.get(AiBatch, bid).collected_at is None


def test_followed_haiku_profiles_are_upgrade_targets(db):
    from test_llm import NOW as N
    from tracker.models import User, UserWatchlist
    _universe(db, 2)
    for t, m in (("S01", config.MODEL_ROUTINE), ("S02", config.MODEL_ROUTINE)):
        db.add(AiOutput(kind="profile", scope_key=t, model=m, input_hash=t, content={"about": []}, sources=[], created_at=N))
    db.add(User(email="a@x.com", created_at=N))
    db.flush()
    db.add(UserWatchlist(email="a@x.com", ticker="S02", added_at=N))
    db.flush()
    assert profiles.upgrade_targets(db) == ["S02"]
