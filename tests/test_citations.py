"""Source-ID validation and wording rules (AGENTS.md rules 3 and 4).

The fixtures are real outputs from the Haiku / Sonnet comparison in docs/model-choice.md.
"""

from tracker.ai import notes, profiles
from tracker.ai.citations import NO_CATALYST, Claim, Source, Validator, unsupported_numbers, wording_problem
from tracker.ai.notes import MoveInput, MoveNoteOut
from tracker.ai.profiles import ProfileOut


def H(id, text, outlet="Reuters"):
    return Source(id=id, kind="headline", text=text, outlet=outlet, url=f"https://www.reuters.com/{id}")


ADBE = MoveInput(subject="ADBE (Adobe)", scope="stock", return_pct=-7.4, market_return_pct=0.3,
                 industry_return_pct=-0.6, industry="Software", date="2026-11-19")
ADBE_SOURCES = [
    H("N1", "Adobe shares tumble as rival unveils free AI design suite"),
    H("N2", "Adobe Falls Most Since March After Analyst Cuts Rating on AI Pricing Pressure", "Bloomberg"),
    H("N3", "Stocks making the biggest moves midday: Adobe, Target, Palo Alto", "CNBC"),
    H("N4", "Target beats on earnings, raises holiday guidance", "Yahoo Finance"),
    H("N5", "Adobe to host investor day in December"),
]

NKE = MoveInput(subject="NKE (Nike)", scope="stock", return_pct=9.1, market_return_pct=-0.2,
                industry_return_pct=1.4, industry="Apparel", date="2026-12-19")
NKE_SOURCES = [
    Source(id="F1", kind="primary", label="8-K item 2.02", url="https://www.sec.gov/f1", text=(
        "Revenues for the fiscal second quarter were $12.4 billion, up 6 percent on a reported basis. Gross margin "
        "increased 180 basis points to 45.9 percent, primarily due to lower product costs and fewer markdowns. "
        "Inventories were $7.1 billion, down 9 percent. The company raised its full-year revenue growth outlook to "
        "mid-single digits from low-single digits. Diluted earnings per share for the quarter were $0.98.")),
    H("N1", "Nike stock soars after earnings beat, guidance raise", "CNBC"),
    H("N2", "Nike's Turnaround Plan Starts to Show Results, CEO Says", "WSJ"),
    H("N3", "Nike Rallies as Analysts Say Worst of China Slump May Be Over", "Bloomberg"),
]


def test_claim_with_unknown_or_missing_source_is_dropped():
    v = Validator(ADBE_SOURCES)
    kept = v.claims("claims", [Claim(text="Reports suggest a downgrade.", source_ids=["N9"]),
                               Claim(text="Reports suggest a downgrade.", source_ids=[]),
                               Claim(text="Reports suggest a downgrade.", source_ids=["N2", "X1"]),
                               Claim(text="Reports suggest a downgrade.", source_ids=["N2"])])
    assert [c.source_ids for c in kept] == [["N2"]]
    assert len(v.checked.dropped) == 3


def test_headline_claim_must_be_hedged_and_must_not_state_a_cause():
    n = [ADBE_SOURCES[1]]
    assert wording_problem("Adobe fell after an analyst cut its rating.", n, "") == "headline-only claim without cautious wording"
    assert wording_problem("Adobe fell because of a downgrade, reports say.", n, "") == "headline-only claim states a cause as fact"
    assert wording_problem("Coverage around the move points to a downgrade, which may have weighed on shares.", n, "") is None


def test_primary_source_allows_firm_causes():
    f = [NKE_SOURCES[0]]
    assert wording_problem("Gross margin rose due to lower product costs.", f, NKE_SOURCES[0].text) is None


def test_beat_needs_an_expectation_in_the_input():
    n = [NKE_SOURCES[1]]
    assert "beat" in wording_problem("Coverage points to the earnings beat.", n, "revenue was $12.4 billion")
    assert wording_problem("Coverage points to results that beat estimates.", n, "consensus estimates were $0.90") is None


def test_numbers_must_come_from_the_input():
    allowed = {"12.4", "45.9", "180"}
    assert unsupported_numbers("Revenue was $12.4 billion and margin 45.9%, up 180 bp.", allowed) == set()
    assert unsupported_numbers("Revenue was $12.5 billion.", allowed) == {"12.5"}
    assert unsupported_numbers("Revenue grew for 3 quarters.", allowed) == set()  # single digits are fine
    assert unsupported_numbers("Margin was 45.90%.", allowed) == set()


def test_sonnet_adobe_note_keeps_hedged_claims_and_drops_unhedged_one():
    out = MoveNoteOut(
        summary="Adobe fell 7.4% while the S&P 500 rose 0.3% and software peers averaged -0.6%, so the drop looks "
                "specific to Adobe. Coverage around the move points to a rival's free AI design tool and an analyst "
                "downgrade over AI pricing pressure. Both come from headlines only, so the cause is not confirmed.",
        claims=[Claim(text="Coverage around the move points to a competitor launching a free AI design suite, which may have weighed on Adobe shares.", source_ids=["N1"]),
                Claim(text="Reports suggest an analyst downgraded Adobe over AI pricing pressure, and that the fall was its largest since March.", source_ids=["N2"]),
                Claim(text="Adobe was also named among the day's big midday movers.", source_ids=["N3"])],
        confidence="medium", ranked_source_ids=["N1", "N2", "N3", "N4"])
    note, checked = notes.validate(out, ADBE, ADBE_SOURCES)
    assert [c.source_ids for c in note.claims] == [["N1"], ["N2"]]
    assert note.summary == out.summary
    assert note.ranked_source_ids == ["N1", "N2", "N3", "N4"]
    assert checked.stored_sources(ADBE_SOURCES) == [
        {"id": "N1", "url": "https://www.reuters.com/N1", "outlet": "Reuters"},
        {"id": "N2", "url": "https://www.reuters.com/N2", "outlet": "Bloomberg"},
        {"id": "N3", "url": "https://www.reuters.com/N3", "outlet": "CNBC"},   # ranked links are kept too
        {"id": "N4", "url": "https://www.reuters.com/N4", "outlet": "Yahoo Finance"}]


def test_haiku_nike_note_loses_the_headline_beat_and_gets_a_safe_summary():
    out = MoveNoteOut(
        summary="Nike rose 9.1% today, while the S&P 500 slipped 0.2% and apparel peers averaged a 1.4% gain. Its "
                "earnings release reported revenue of $12.4 billion, up 6%, and a raised full-year revenue outlook. "
                "Coverage around the move points to the earnings beat and guidance raise.",
        claims=[Claim(text="The earnings release reported fiscal second-quarter revenue of $12.4 billion, up 6%.", source_ids=["F1"]),
                Claim(text="Gross margin rose 180 basis points to 45.9%, mainly from lower product costs and fewer markdowns.", source_ids=["F1"]),
                Claim(text="Coverage around the move points to the earnings beat and the guidance raise.", source_ids=["N1"]),
                Claim(text="Some coverage reports that analysts think the worst of the China slump may be over.", source_ids=["N3"])],
        confidence="high", ranked_source_ids=["F1", "N1", "N3", "N2"])
    note, checked = notes.validate(out, NKE, NKE_SOURCES)
    assert [c.source_ids for c in note.claims] == [["F1"], ["F1"], ["N3"]]
    assert "beat" not in note.summary
    assert note.summary == note.claims[0].text
    assert note.confidence == "high"  # a primary source explains it
    assert {d.where for d in checked.dropped} == {"claims", "summary"}


def test_high_confidence_needs_a_primary_source():
    out = MoveNoteOut(summary="Coverage around the move points to a downgrade.", confidence="high",
                      claims=[Claim(text="Reports suggest an analyst cut the rating.", source_ids=["N2"])])
    note, _ = notes.validate(out, ADBE, ADBE_SOURCES)
    assert note.confidence == "medium"


def test_no_catalyst_note_passes():
    lin = MoveInput(subject="LIN (Linde)", scope="stock", return_pct=-5.3, market_return_pct=-0.5,
                    industry_return_pct=-0.9, industry="Chemicals", date="2026-11-20")
    out = MoveNoteOut(summary="Linde fell 5.3% while the S&P 500 fell 0.5% and chemicals peers averaged -0.9%. "
                              + NO_CATALYST, confidence="medium", claims=[], ranked_source_ids=[])
    note, checked = notes.validate(out, lin, [H("N1", "Dow slips as Treasury yields climb")])
    assert note.summary.endswith(NO_CATALYST) and note.confidence == "low" and not checked.dropped


def test_invented_number_in_summary_is_replaced():
    out = MoveNoteOut(summary="Adobe fell 7.4%, its worst day in 14 months.", confidence="low",
                      claims=[Claim(text="Reports suggest an analyst cut the rating.", source_ids=["N2"])])
    note, checked = notes.validate(out, ADBE, ADBE_SOURCES)
    assert "14" not in note.summary and checked.dropped[0].reason.startswith("numbers")


COST_SOURCES = [
    Source(id="P0", kind="own", text="overview: Membership warehouse retailer with about 890 warehouses, most in the US. bull: Renewal rates near 90%."),
    Source(id="M1", kind="metrics", text="revenue TTM $269.1B; revenue growth YoY 7.8%; operating margin 3.6%; net margin 2.9%; diluted EPS TTM $18.21; net debt/EBITDA -0.6x"),
    Source(id="K1", kind="primary", text="As of September 1, 2026, we operated 914 warehouses worldwide: 629 in the United States and Puerto Rico. We had 79.6 million paid household members at year end. Our membership fee revenue was $5.3 billion."),
    Source(id="K2", kind="primary", text="Net sales increased 8% driven by comparable sales growth of 6%. The renewal rate was 92.3% in the U.S. and Canada and 89.9% worldwide. We plan to open 30 net new warehouses in fiscal 2027, including our first locations in Sweden."),
    Source(id="K3", kind="primary", text="Tariffs and changes in trade policy could increase our merchandise costs."),
    H("N1", "Costco Shares Have Become Too Expensive, Some Investors Say", "Bloomberg"),
]


def test_profile_keeps_valid_claims_and_drops_invented_ones():
    out = ProfileOut(
        overview=[Claim(text="Costco operated 914 warehouses worldwide as of September 1, 2026.", source_ids=["K1"]),
                  Claim(text="It has about 95 million members.", source_ids=["K1"])],
        strategy_and_trajectory=[Claim(text="It plans 30 net new warehouses in fiscal 2027, including Sweden.", source_ids=["K2"])],
        bull_case=[Claim(text="Net debt to EBITDA is -0.6x, a net cash position.", source_ids=["M1"])],
        bear_case=[Claim(text="A headline reports that some investors think the shares have become too expensive.", source_ids=["N1"]),
                   Claim(text="The shares are too expensive.", source_ids=["N1"])],
        what_changed="The warehouse count is now 914, up from about 890.")
    profile, checked = profiles.validate(out, COST_SOURCES)
    assert len(profile.overview) == 1 and len(profile.bear_case) == 1
    assert profile.what_changed.startswith("The warehouse count")
    assert sorted(d.reason.split(":")[0] for d in checked.dropped) == ["headline-only claim without cautious wording", "numbers not in the input"]


def test_profile_with_an_empty_section_is_not_published():
    out = ProfileOut(overview=[Claim(text="Costco operated 914 warehouses.", source_ids=["K1"])],
                     strategy_and_trajectory=[Claim(text="It plans 30 new warehouses.", source_ids=["K2"])],
                     bull_case=[Claim(text="Shares will double.", source_ids=["Z1"])],
                     bear_case=[Claim(text="Tariffs could raise costs.", source_ids=["K3"])])
    profile, _ = profiles.validate(out, COST_SOURCES)
    assert profile is None


def test_prompts_load_with_rules_inlined():
    for system in (notes.system_prompt(), profiles.system_prompt()):
        assert "{rules}" not in system and "kind=headline" in system
