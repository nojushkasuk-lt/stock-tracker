# Model choice: Haiku 5.5 vs Sonnet 5.5

Checked 2026-11-23, before writing `tracker/ai/llm.py`.

## Docs check

| | Haiku 5.5 (`claude-haiku-5-5`) | Sonnet 5.5 (`claude-sonnet-5-5`) |
|---|---|---|
| Price / MTok (in / out) | $0.10 / $0.50 up to 100k-token prompts; $0.50 / $2.50 above | $2 / $10 |
| Batch API | 50% off | 50% off |
| Structured outputs | yes | yes |
| Sampling (`temperature` etc.) | leave out | 400 if sent |
| Default effort | `medium` | `high` |

Haiku 5.5 uses the newer tokenizer (~30% more tokens than Haiku 4.5 for the same text), so `llm.py` counts
tokens with the API before each call instead of estimating.

## Side-by-side test

Same prompt and inputs for both models (run as Claude Code subagents, no API key used): three move notes and
one profile update, with traps built in. Inputs were realistic but made up, so every claim could be checked.

| Trap | Haiku | Sonnet |
|---|---|---|
| A1 Adobe -7.4%, headline-only sources, one off-topic headline (Target), one stale (investor day) | cautious wording, dropped both irrelevant sources | same |
| A2 Nike +9.1%, 8-K earnings release read in full + headlines | firm claims only from the 8-K; headline claims hedged | same, and called the 8-K "the likely driver" |
| A2 "earnings beat" appears only in a headline (no estimates in input) | repeated it, hedged | repeated it, hedged |
| A3 Linde -5.3%, nothing relevant | "no clear catalyst found yet", no claims | same |
| Invented numbers / unknown source IDs | none | none |
| B Costco profile from 10-K excerpts + computed metrics | correct, a bit thinner: no business-model claim, 2 bull points; softened "we attribute" to "partly attributes" | fuller (business model, EPS, net cash); one muddled comparison in "what changed" |

**Verdict:** for notes Haiku is as good as Sonnet. For profiles it is a small downgrade (less complete, one
slight misquote of the filing). Keep the plan: Haiku for notes and summaries, Sonnet for filing-based profile
updates (rare: about 4 filings a year per followed company, so the cost difference is small).

## Prompt fixes found by the test

- Say that "beat" / "miss" may only be used when the input contains the expectation it beats.
- Keep the filing's own attribution wording; do not soften or strengthen it.
- Start the "no clear catalyst found yet" sentence with a capital letter when it starts a sentence.

Caveat: one sample per model, and the subagents ran inside Claude Code rather than through the bare API.
The Day 4 model test (20 real moves) is the fuller check.

## First live API calls (2026-11-23)

Same inputs through `tracker/ai/llm.py` with the new prompts. Cost: Haiku notes $0.0003 each, Sonnet profile $0.011.

- Nike (Haiku): no "beat" this time; firm claims only from the 8-K; headline claims hedged. Nothing dropped.
- Adobe (Haiku): hedged claims kept; one uncited claim restating the move was dropped by the validator.
- Costco (Sonnet): all claims passed, but one mislabels a figure ("net margin of 3.6% at the operating level";
  3.6% is the operating margin). The number check only confirms a number appears in the input, not that it is
  attached to the right label. Keep this in mind for the Day 7 hand-check; a label-aware check is possible later.
