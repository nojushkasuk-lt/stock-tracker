"""Profile on the stock page: read-only service, source links, Markdown-safe text."""

from contextlib import contextmanager
from datetime import datetime

from sqlalchemy.orm import Session

from tracker import services
from tracker.db import create_tables, make_engine
from tracker.models import AiOutput
from ui.text import md

CONTENT = {
    "overview": [{"text": "Costco runs membership warehouses.", "source_ids": ["K1"]},
                 {"text": "Revenue was $303.2 billion.", "source_ids": ["M1", "K1", "K1"]}],
    "strategy_and_trajectory": [{"text": "It plans 33 new warehouses.", "source_ids": ["K2", "P0"]}],
    "bull_case": [{"text": "Renewal rates are high.", "source_ids": ["K1"]}],
    "bear_case": [{"text": "Tariffs could raise costs.", "source_ids": ["K2"]}],
    "what_changed": "Warehouse count rose.",
    "dropped": [],
}
SOURCES = [{"id": "M1", "url": None, "outlet": None},
           {"id": "K1", "url": "https://www.sec.gov/k.htm", "outlet": "SEC EDGAR"},
           {"id": "K2", "url": "https://www.sec.gov/k.htm", "outlet": "SEC EDGAR"},
           {"id": "P0", "url": None, "outlet": None}]


def use_db(tmp_path, monkeypatch, rows=()):
    engine = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    create_tables(engine)
    with Session(engine) as s:
        s.add_all(rows)
        s.commit()

    @contextmanager
    def scope():
        with Session(engine) as s:
            yield s

    monkeypatch.setattr(services, "session_scope", scope)


def test_profile_sections_with_deduplicated_source_links(tmp_path, monkeypatch):
    use_db(tmp_path, monkeypatch, [AiOutput(kind="profile", scope_key="COST", model="claude-sonnet-5-5", input_hash="h",
                                            content=CONTENT, sources=SOURCES, created_at=datetime(2026, 11, 23, 9))])
    p = services.get_profile("cost")
    assert [t for t, _ in p.sections] == ["Overview and sector", "Strategy and trajectory", "Bull case", "Bear case"]
    rev = p.sections[0][1][1]
    assert [(l.label, l.url) for l in rev.sources] == [("our figures from SEC filings", None), ("SEC EDGAR", "https://www.sec.gov/k.htm")]
    assert [(l.label, l.url) for l in p.sections[1][1][0].sources] == [("SEC EDGAR", "https://www.sec.gov/k.htm")]  # P0 not linked
    assert p.what_changed == "Warehouse count rose." and p.updated == "2026-11-23"


def test_no_profile_means_none(tmp_path, monkeypatch):
    use_db(tmp_path, monkeypatch)
    assert services.get_profile("COST") is None


def test_model_text_cannot_inject_markdown_or_math():
    assert md("Revenue $5.9 billion and $1.3 billion") == r"Revenue \$5.9 billion and \$1.3 billion"
    assert md("[click](https://evil.example)") == r"\[click\]\(https://evil.example\)"
