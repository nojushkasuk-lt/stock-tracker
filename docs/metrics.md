# How the numbers are computed

Everything here comes from SEC filings (XBRL "company facts" for 10-K and 10-Q forms), computed in Python in
`tracker/analysis/metrics.py`. The AI never produces these numbers (AGENTS.md rule 3). Where a figure cannot be
computed honestly, the app shows "n/a" with the reason.

## Definitions

- **Trailing twelve months (TTM)** = last full fiscal year + this year's year-to-date - the same year-to-date a year earlier.
  When the latest report is a 10-K, TTM is simply that year.
- **Operating margin** = TTM operating income / TTM revenue, **as filed under US GAAP** (not adjusted for one-off charges).
  Not shown for companies that do not report operating income (many banks, insurers, pharma and energy companies).
- **Net margin** = TTM net income / TTM revenue.
- **Revenue growth (YoY)** = TTM revenue / TTM revenue one year earlier - 1.
- **EPS (diluted)** = TTM diluted earnings per share, built the same way as TTM.
- **EBITDA** = TTM operating income + TTM depreciation and amortization. If a company reports no single D&A total, we use
  depreciation + amortization of intangibles when both exist and mark EBITDA as approximate.
- **Net debt** = total debt (incl. commercial paper and short-term borrowings) - cash - current marketable securities.
  Long-term investments are not counted as cash. A company that reports no debt at all is treated as debt-free.
- **Net debt / EBITDA** is not shown for banks, capital-markets firms, insurers and payment networks (not comparable),
  or when EBITDA is zero or negative.
- Several XBRL tags can describe one concept (revenue was tagged differently over the years); they are merged by priority.
  When a period is restated, the latest filing wins. Companies that reorganized under a new SEC registrant list their old
  registrant in `config/predecessors.csv` so history carries over.

## Check against an outside source (2026-11-22, stockanalysis.com statistics pages)

| | AAPL ours / source | KO ours / source | PG ours / source |
|---|---|---|---|
| Revenue (TTM) | $478.83B / $478.83B | $51.05B / $51.05B | $87.92B / $87.92B |
| Net margin | 27.60% / 27.60% | 28.65% / 28.65% | 18.23% / 18.23% |
| EPS (diluted, TTM) | 8.98 / 8.98 | 3.39 / 3.39 | 6.64 / 6.64 |
| Operating margin | 33.01% / 33.01% | 30.04% / 32.17% | 22.55% / 24.88% |
| EBITDA (TTM) | $171.49B / $171.49B | $16.36B / $17.44B | $23.04B / $25.09B |
| Net debt | $23.39B / net cash $42.46B | $28.09B / $25.88B | $20.21B / $23.56B |

Differences are definitional, not arithmetic:

- **Operating income (KO, PG):** the outside source appears to add back one-off charges; we report the filed GAAP figure.
  For KO we checked the filed facts: FY2025 13.76B + 9M 2026 13.50B - 9M 2025 11.92B = 15.34B, so the TTM math is right.
  EBITDA differs by the same amount.
- **Net debt:** the source also counts long-term investments (e.g. Apple's non-current marketable securities) as cash;
  we do not, which makes our net debt larger.
