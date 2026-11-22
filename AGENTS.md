# AGENTS.md — Stock Tracker

Instructions for any coding agent (Claude Code, Codex) working in this repo. Read this file and PLAN.md before doing anything.

## What this is

A public website for following US stocks. Anyone can open a read-only demo of the 20 largest US companies. Signed-in users (Google) pick up to 15 stocks from the 100 largest US companies and get:

- a live-style price chart and quote for each stock (TradingView widgets, delayed data)
- fundamentals and ratios computed from SEC filings (EDGAR)
- an AI company profile (overview and sector, strategy and trajectory, bull case, bear case) with source links, updated when the company files a new report
- big-move alerts: when a stock moves 5% or more in a day, the app works out whether the cause is market-wide, industry-wide or specific to the stock, then shows a short AI note and links to coverage
- a market page that activates when the S&P 500 moves sharply, with one shared note, links and free TradingView widgets (heatmap, economic calendar)
- a news-source setting: each user chooses which outlets (Bloomberg, WSJ, NYT, ...) their coverage links come from
- a rate-limited "Refresh now" button

The app does not republish articles. It shows headlines, outlets, links and its own short notes, and sends the user to the outlet.

## Stack

- Python 3.12
- Streamlit for the UI (may be replaced by NiceGUI later, so keep the UI thin)
- SQLAlchemy 2.x; SQLite locally, Neon Postgres when deployed (only `DATABASE_URL` changes)
- TradingView free embed widgets for all price charts, quotes, heatmap and economic calendar (embedded with `st.iframe`, since `st.components.v1.html` is deprecated; keep the TradingView link on each widget). `st.iframe` gives an HTML string same-origin access to the app, so only ever pass HTML that `ui/tradingview.py` builds from a validated ticker, never user or model text. `data:` URLs (which would isolate the widget) did not render the widgets
- Plotly only for charts of our own EDGAR-derived numbers (revenue, margins)
- httpx for HTTP, pydantic for data models and LLM output validation, pytest for tests
- Anthropic API: `claude-haiku-5-5` for routine work, `claude-sonnet-5-5` for filing-based profile updates (Batch API where results can wait)
- Data: SEC EDGAR (filings, XBRL numbers, SIC codes), a swappable price provider (see rule 13), Brave News Search API (live queries only), outlet RSS feeds as fallback
- Scheduling: GitHub Actions. Hosting: Streamlit Community Cloud.

## Folder layout

```
app.py                  # UI only
ui/
  tradingview.py        # builds TradingView widget HTML (chart, symbol info, heatmap, calendar)
tracker/
  config.py             # settings from env / st.secrets: thresholds, caps, model names
  db.py                 # engine, session
  models.py             # SQLAlchemy models (mirror schema.sql)
  services.py           # the ONLY tracker module app.py imports
  data/
    prices.py           # PriceProvider interface: daily returns only (see rule 13)
    charts.py           # chart data for the custom chart: in-memory cache, off in prod (see rule 13)
    providers/          # one file per provider (yfinance_dev.py, alphavantage.py, ...)
    edgar.py            # EDGAR client (User-Agent, rate limit), submissions, domestic-filer check
    listings.py         # spot new exchange listings (IPOs) from the SEC ticker file
    news.py             # Brave live search, outlet filter, transient cache, monthly search cap; RSS fallback
    filings.py          # EDGAR submissions -> new 10-Q / 10-K / 8-K rows; triggers fundamentals refresh
  analysis/
    metrics.py          # TTM, margins, growth, EPS, net debt/EBITDA from EDGAR figures (definitions in docs/metrics.md)
    moves.py            # move detection and the market -> industry -> stock ladder
  ai/
    llm.py              # single wrapper: all model calls, budget check, cost log
    prompts/            # one .md file per prompt
    profiles.py         # filing-triggered profile updates (Sonnet)
    notes.py            # market / industry / stock notes and link ranking (Haiku)
    digests.py          # Monday/Thursday market summary (Haiku)
jobs/
  daily.py              # daily returns, filings check, move detection, notes
  digest.py             # Monday/Thursday market summary
  universe.py           # weekly: re-rank by market cap (entries, exits, demo top 20)
  fundamentals.py       # fetch EDGAR financial figures (python -m jobs.fundamentals [TICKER ...] [--all])
  profiles.py           # process queued profile updates
config/
  universe.csv          # seed for the universe table: ticker, cik, name, industry, rank, is_demo (after the first load jobs/universe.py owns rank, demo and active)
  candidates.csv        # next ~100 companies the weekly job may promote into the top 100
  predecessors.csv      # tickers that moved to a new SEC registrant: old CIK whose history to merge
  pins.csv              # tickers that always stay in the universe (starts empty; escape hatch for mega-IPOs or edge cases)
  outlets.toml          # outlets users can choose from: name, domain, paywall (TOML: read by the standard library, no extra dependency)
docs/
  metrics.md            # how each number is computed and how it was checked
  data-licensing.md     # which data source is used, what its terms allow, written permissions received
tests/
.github/workflows/
```

## Universe definition

The universe is the 100 largest US-listed companies by market cap **as reported by the price provider** (weekly job). It is not float-adjusted and may differ from other ranking sites, especially for companies with several share classes. New US domestic filers are picked up from the SEC ticker file within a week. Foreign issuers (20-F filers) are excluded in v1.

## Rules

1. **`app.py` only displays.** It imports `tracker/services.py` and `ui/`. It calls functions such as `get_watchlist(email)`, `get_profile(ticker)`, `get_move_note(ticker)`, `request_refresh(email, ticker)`. It never calls an external API, an LLM or the database directly.
2. **Every model call goes through `tracker/ai/llm.py`.** The wrapper checks the monthly budget before calling, logs tokens and cost to `usage_log`, and reads model names from config. Nothing else imports the Anthropic SDK.
3. **Numbers never come from the model.** Ratios and filing figures are computed in Python from EDGAR. Move sizes come from the price provider. The model receives them and explains them.
4. **Every AI claim cites a source.** Inputs carry source IDs; outputs are validated with pydantic; drop any claim whose source ID isn't in the input. Headline-based notes use cautious wording ("coverage around the move points to ...") and never state a cause as fact. Firm causal statements are allowed only when a primary source read in full supports them (an EDGAR 8-K or earnings release). If nothing explains a move, say "no clear catalyst found yet".
5. **Keep each prompt under 100,000 tokens.** Haiku's price rises fivefold above that. Send filing sections (MD&A, earnings release), not whole filings.
6. **Caps (all in config):**
   - 3 refreshes per user per day; 300 per month in total; a refresh of a ticker is shared with everyone for 6 hours.
   - 10 "more coverage" live searches per user per day.
   - All AI jobs stop when month-to-date cost reaches `MONTHLY_BUDGET_USD` (default 8.00).
   - All live news searches stop at `MONTHLY_SEARCH_CAP` (default 900, inside Brave's monthly free credit).
   - The market note is refreshed at most every `MARKET_NOTE_MIN_INTERVAL_HOURS` (default 3).
7. **Demo mode is read-only.** No database writes, no AI calls, no live searches, no refresh button. It shows notes the daily job already generated.
8. **AI coverage only for stocks someone follows** plus the 20 demo stocks. A stock that drops out of the top 100 is soft-removed (`universe.active = FALSE`): current followers keep it, nobody new can add it.
9. **EDGAR:** send a `User-Agent` with a name and contact email from config; stay under 10 requests per second.
10. **Secrets** live in `.env` (local), `st.secrets` (Streamlit Cloud) and GitHub Actions secrets. Never commit them. Never put `ANTHROPIC_API_KEY` in a shell profile: Claude Code would then bill the API instead of the subscription.
11. **Public text:** never reproduce article text. Show headline, outlet, link and our own note. Headlines come from live search results and are not stored (rule 13).
12. **Footer:** "For information only. Not investment advice." plus "News search by Brave Search API" (Brave's free credit requires the credit line). Keep the TradingView link on every widget.
13. **Data licensing. Read this twice.**
    - Most free price and news APIs are licensed for the account holder's own use only, not for showing data to other people. Do not add one to the public site without recording its terms in `docs/data-licensing.md`.
    - On the public site, prices, charts, quotes and market-wide visuals are shown only through TradingView widgets. We never store price history or OHLC.
    - **Dev-only exception (owner decision, 2026-11-22):** the custom chart (`ui/chart.py`, `tracker/data/charts.py`) may show provider closing prices when `APP_ENV=local`, fetched live and cached in memory only (never written to the database), so the real design can be built now. In prod `CHART_PROVIDER` defaults to `none` and the app falls back to the TradingView widgets. A licensed provider is switched on only after `docs/data-licensing.md` records written permission or a display-capable plan.
    - The price provider is used only to compute daily percent changes (stocks and the S&P 500 via SPY). Store only those in `daily_returns`. Put every provider behind the `PriceProvider` interface so it can be swapped by config (`PRICE_PROVIDER`).
    - `yfinance_dev.py` is for local development only. It must raise an error when `APP_ENV=prod`.
    - Do not use Finnhub. Its free plan is personal-use.
    - Brave results must not be stored or cached beyond transient use: keep them in a short in-memory cache (under 1 hour). What we do store is our own note plus the URL and outlet it cites (gray area; revisit if Brave objects).
    - Do not deploy publicly until the data-licensing gate in PLAN.md (Day 6) is ticked.
14. **Attribution ladder** (`analysis/moves.py`). Thresholds live in config:
    - Market: S&P 500 (SPY) daily move of at least `MARKET_ALERT_PCT` (2.0) raises an alert; at least `MARKET_MAJOR_PCT` (3.0) is "major". One shared market note per day (rule 6).
    - A stock is a candidate when its move is at least `MOVE_THRESHOLD_PCT` (5.0). Demo stocks use `DEMO_MOVE_THRESHOLD_PCT` (3.0) so the demo is not empty.
    - If the market alert is on and the stock's move differs from the index move by less than `RESIDUAL_PCT` (3.0), scope = `market`: attach the shared market note, no search.
    - Else, if at least `INDUSTRY_MIN_PEERS` (3) tracked peers in the same industry have an average move of at least `INDUSTRY_MOVE_PCT` (3.0) and the stock differs from that average by less than `RESIDUAL_PCT`, scope = `industry`: one shared note per industry per day, one search.
    - Else scope = `stock`: its own live search and note.
    - Recheck pending moves after 6–12 hours.

## How to work

- Work through PLAN.md in order. One task at a time.
- After each working step: run `pytest`, then commit with a clear message.
- At the end of a session: tick the boxes in PLAN.md and add two lines to its session log (what was done, what's next).
- Only one agent works in the repo at a time.
- Ask before adding a new dependency or service; add it to `requirements.txt`.
- Tests are required for: ratios, move detection and the attribution ladder, source-ID validation, caps and budget checks, and the `yfinance_dev` prod guard.

## Commands

```
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
pytest
python -m jobs.daily
```
