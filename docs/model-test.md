# Day 4 model test: 20 real moves through Haiku 5.5

Run 2026-11-23. Owner decision: test Haiku only (no DeepSeek / GLM; Haiku and Sonnet were judged stronger at a
similar price). Moves come from `daily_returns`; links are live Brave results from the chosen outlets for the two
days before and the day of the move; the earnings release (8-K item 2.02 EX-99) is added when it was filed before
that day's close. Headlines were read on screen for grading and not stored (rule 13), so they are paraphrased here.

Cost: about $0.0005 per headline-only note, $0.002 with an earnings release (8-12k tokens). All 20: about $0.015.

| # | Move | Scope | Sources | Relevant first | Unsupported claim | Cause stated as fact from headlines |
|---|---|---|---|---|---|---|
| 1 | PANW +9.9%, Nov 18 | stock | headlines (results came after the close) | yes (acquisition news) | no | no |
| 2 | UNH -10.2%, Nov 18 | stock | headlines | yes (proposed CMS anti-fraud rule) | no | no |
| 3 | TJX +8.0%, Nov 18 | stock | earnings release + headlines | yes | no | no |
| 4 | CRM -9.5%, Nov 17 | stock | headlines | yes (AI-agent fears, IPO rotation) | no | no |
| 5 | CSCO -6.2%, Nov 13 | stock | earnings release + headlines | yes (margins, guidance) | no | no |
| 6 | DELL +11.8%, Nov 11 | stock | headlines | weak sources; hedged | no | no |
| 7 | IBKR +6.3%, Nov 11 | stock | none found | n/a: "No clear catalyst found yet" | no | no |
| 8 | APP +31.0%, Nov 5 | stock | earnings release + headlines | yes | no | no |
| 9 | BKNG +9.8%, Nov 4 | stock | earnings release + headlines | yes; mixed coverage reported as mixed | no | no |
| 10 | GEV -9.3%, Nov 4 | stock | headlines | yes (election and data-centre demand fears) | no | no |
| 11 | LMT -6.9%, Nov 4 | stock | headlines | first run: a small legal settlement (hedged); after fix: no catalyst | no | no |
| 12 | MSFT +6.7%, Nov 4 | stock | headlines | yes (post-election rally) | no | no |
| 13 | ORCL -8.8%, Nov 2 | stock | headlines | yes ($20 billion stock and bond sale) | no | no |
| 14 | CVNA -5.3%, Nov 19 | stock | headlines, none relevant | n/a: no catalyst | no | no |
| 15 | SCCO -5.9%, Nov 18 | stock | headlines | yes (copper price drop) | no | no |
| 16 | TSLA -7.6%, Nov 20 | stock | headlines | yes (AI sell-off) | no | no |
| 17 | Semiconductors -5.2%, Nov 16 | industry | headlines | yes; ignored off-topic chip stories | no | no |
| 18 | Medical devices +5.5%, Nov 4 | industry | none found | n/a: no catalyst | no | no |
| 19 | S&P 500 -4.4%, Nov 5 | market | headlines | yes (AI / tech sell-off) | no | no |
| 20 | S&P 500 -3.6%, Nov 20 | market | headlines | yes (AI sell-off, correction) | no | no |

Validation dropped nothing in the final runs: the prompt rules were followed, so the checks in `citations.py`
acted as a safety net only.

## Problems found and fixed

- **News after the move.** A search window that ended the day after the move let Haiku explain PANW's +9.9% with
  results released after that day's close (the next day's +6.4% was the earnings reaction). Searches for a move
  must end on the move date, and the prompt now says later events cannot explain it.
- **Earnings release not found.** TJX names its exhibit `tjxq3fy27earningspressrele.htm`; the exhibit is now found
  by the "EX-99" type on the filing index page, with the file name as a fallback.
- **Talking about its inputs.** 6 of 20 notes said things like "no peer average was provided" or "only a headline
  was seen". The prompt now forbids this (the page labels headline-based notes itself).
- **Long summaries.** Several were over 60 words; `notes.trim_summary` keeps whole sentences up to 60 words.
- **Wrong subject.** The medical-devices note with no sources called the industry "the stock". The prompt now
  says to name the subject as given.
- **Small news for a big move.** LMT's -6.9% was pinned (hedged) on a small legal settlement. The prompt now says a
  headline must be plausibly big enough to explain the move; the rerun said "No clear catalyst found yet".

## Verdict

Haiku 5.5 is good enough for move notes. For Day 5: build industry and market queries in code (the test used
hand-written ones; "medical device" stocks found nothing), and keep the search window ending on the move date.
