"""ai_outputs: input-hash cache, validated content only, no headline text stored."""

from datetime import datetime

from sqlalchemy import select

from test_citations import ADBE, ADBE_SOURCES
from test_llm import NOW, db, fake  # noqa: F401  (db fixture)
from tracker.ai import notes, outputs
from tracker.ai.citations import Claim
from tracker.ai.notes import MoveNoteOut
from tracker.data.news import NewsLink
from tracker.models import AiOutput, UsageLog

GOOD = MoveNoteOut(summary="Coverage around the move points to an analyst downgrade.", confidence="medium",
                   claims=[Claim(text="Reports suggest an analyst cut the rating.", source_ids=["N2"]),
                           Claim(text="Shares fell because of the rival product.", source_ids=["N1"])],
                   ranked_source_ids=["N2", "N1"])


def write(db, client, m=ADBE, sources=ADBE_SOURCES):
    return notes.write_note(db, m, sources, ticker="ADBE", client=client, now=NOW)


def test_note_is_validated_stored_and_reused(db):
    c = fake(parsed=GOOD)
    row = write(db, c)
    assert (row.kind, row.scope_key, row.confidence) == ("stock_note", "ADBE", "medium")
    assert [cl["source_ids"] for cl in row.content["claims"]] == [["N2"]]
    assert row.content["dropped"][0]["reason"] == "headline-only claim without cautious wording"
    assert write(db, c).id == row.id
    assert len(c.messages.parse_calls) == 1
    assert len(db.execute(select(UsageLog)).scalars().all()) == 1


def test_new_inputs_mean_a_new_call(db):
    c = fake(parsed=GOOD)
    write(db, c)
    write(db, c, m=ADBE.model_copy(update={"return_pct": -8.0}))
    assert len(c.messages.parse_calls) == 2
    assert outputs.latest(db, "stock_note", "ADBE").content["claims"]


def test_stored_sources_hold_only_id_url_outlet_and_no_headlines(db):
    row = write(db, fake(parsed=GOOD))
    assert row.sources == [{"id": "N1", "url": "https://www.reuters.com/N1", "outlet": "Reuters"},
                           {"id": "N2", "url": "https://www.reuters.com/N2", "outlet": "Bloomberg"}]
    stored = str(row.content) + str(row.sources)
    assert not any(s.text in stored for s in ADBE_SOURCES)


def test_market_and_industry_notes_are_shared_keys(db):
    m = ADBE.model_copy(update={"scope": "industry"})
    assert notes.scope_key(m) == "industry:Software"
    assert notes.scope_key(ADBE.model_copy(update={"scope": "market"})) == "market"


def test_links_become_headline_sources():
    links = [NewsLink("Adobe slides", "https://www.reuters.com/x", "Reuters", "reuters.com", datetime(2026, 11, 19, 15), False)]
    [s] = notes.sources_from_links(links)
    assert (s.id, s.kind, s.outlet, s.date) == ("N1", "headline", "Reuters", "2026-11-19")


def test_prompt_version_changes_the_hash(monkeypatch):
    h1 = outputs.input_hash("m", "s", "u", MoveNoteOut)
    monkeypatch.setattr(outputs, "PROMPT_VERSION", "2")
    assert outputs.input_hash("m", "s", "u", MoveNoteOut) != h1


def test_nothing_stored_when_no_row_survives(db):
    from tracker.ai.profiles import ProfileOut
    from test_citations import COST_SOURCES
    from tracker.ai import profiles
    bad = ProfileOut(overview=[Claim(text="Made up.", source_ids=["Z9"])])
    row = outputs.generate(db, kind="profile", scope_key="COST", job="profiles", task="profile", system="s", user="u",
                           output_model=ProfileOut, sources=COST_SOURCES,
                           validate=lambda o: profiles.validate(o, COST_SOURCES), client=fake(parsed=bad), now=NOW)
    assert row is None and db.execute(select(AiOutput)).first() is None
