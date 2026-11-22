# PLAN.md — Stock Tracker

## Decisions

- Public site. Google sign-in for users; "View demo" skips sign-in and shows the 20 largest US companies, read-only.
- Users pick up to 15 stocks from the 100 largest US companies (`universe` table). US stocks only for v1; the `region` column is there for later.
- Display: TradingView free widgets for charts, quotes, heatmap and economic calendar. Fundamentals and ratios from EDGAR. No P/E, VaR or beta in v1 (P/E needs a price; the TradingView symbol-info widget shows it).
- Moves: a daily percent change of 5% or more triggers an alert. The app decides market vs industry vs stock before searching anything (AGENTS.md rule 14).
- News: link-based. Live Brave search, filtered to the outlets each user picks; the AI writes a short note and ranks links. Headline-only wording for paywalled outlets.
- Models: Haiku 5.5 for notes and the Monday/Thursday summary. Sonnet 5.5 for profile updates when a company files a 10-Q, 10-K or earnings 8-K.
- Streamlit first; UI kept thin so it can move to NiceGUI later.
- Budget: AI hard stop at $8/month (prepaid credit, auto top-up off); live searches capped at 900/month (Brave's free monthly credit).
- Price source: undecided. Free tiers are personal-use. Plan: ask Alpha Vantage (open-source/educational key) for written permission. Development uses yfinance locally only. Do not deploy publicly before the Day 6 gate.

## Day 0 — Setup (evening)

- [ ] Accounts: GitHub, Anthropic Console (prepaid credit, auto top-up off), Brave Search API (card needed; keep spending cap), Google Cloud (OAuth client). No Finnhub.
- [ ] Email Alpha Vantage (premium@alphavantage.co) asking for written permission to use their API for a non-commercial public portfolio site (public GitHub repo, 100 US stocks, daily percent changes only, charts via TradingView). Optional: the same to Tiingo sales. Save replies in `docs/data-licensing.md`.
- [x] Install Python 3.12, Git, VS Code, Claude Code, Codex
- [x] Repo with AGENTS.md, PLAN.md, schema.sql, `.gitignore` (including `.env`, `.venv`, `*.db`), `.env.example`, `requirements.txt`, `docs/data-licensing.md`
- [x] `app.py` shows a placeholder page with `streamlit run app.py`

## Day 1 — Data foundation and display

- [ ] `models.py` from schema.sql; `db.py`; tables created in SQLite
- [ ] `config/universe.csv`: the 100 largest US companies with CIK, name, industry (own labels or EDGAR SIC codes, not GICS), rank; top 20 flagged `is_demo`. I (the owner) verify the list by hand.
- [ ] `PriceProvider` interface and `yfinance_dev.py` (blocked when `APP_ENV=prod`); `daily_returns` filled for the universe and SPY
- [ ] `ui/tradingview.py`: chart and symbol-info widgets; stock page shows them
- [ ] Done when: picking a demo ticker shows its chart and quote

## Day 2 — Fundamentals

- [ ] EDGAR XBRL companyfacts → `fundamentals`
- [ ] Ratios: operating margin, net margin, net debt/EBITDA, revenue growth (YoY), diluted EPS
- [ ] Metric cards and a Plotly chart of revenue and margins on the stock page
- [ ] Tests for every ratio
- [ ] Done when: ratios match a trusted source for 3 companies

## Day 3 — News links and filings

- [ ] `news.py`: Brave live news search with a transient cache (under 1 hour) and no storage of results
- [ ] **Check whether Brave can restrict results to named outlets** (e.g. a `site:` operator). If not, fall back to each outlet's RSS feed matched by company name. Record the answer in `docs/data-licensing.md`.
- [ ] `config/outlets.yaml` (Bloomberg, WSJ, NYT, FT, Reuters, CNBC, ...)
- [ ] EDGAR submissions check → new 10-Q / 10-K / 8-K rows in `filings`
- [ ] Stock page: "More coverage" button with live, outlet-filtered links
- [ ] Market page: TradingView heatmap and economic calendar widgets; static Fed and Treasury links
- [ ] Done when: a stock returns links from the chosen outlets only, nothing is stored, and a new filing is detected

## Day 4 — AI layer

- [ ] `llm.py`: one wrapper, budget check, cost log, model names from config
- [ ] Prompts in `ai/prompts/`; pydantic output models; source-ID validation; cautious wording for headline-only notes
- [ ] Profile update from a filing (Sonnet); short stock / industry / market notes and link ranking (Haiku)
- [ ] Cache outputs by input hash
- [ ] Dev-only model test (not deployed): 20 recent real moves through Haiku, DeepSeek V4.1 Flash and GLM-5.3-Flash. Record: relevant links ranked first yes/no, any unsupported claim, any claim stated as certain when only a headline was seen.
- [ ] Done when: a profile shows only claims with valid sources and a note never states a cause as fact from headlines alone

## Day 5 — Users, moves and the ladder

- [ ] Google sign-in (`st.login`), `users`, `user_watchlist`, `user_outlets`; setup page to pick stocks (max 15) and outlets
- [ ] Demo mode: read-only, no AI calls, no searches
- [ ] `moves.py`: detection and the market → industry → stock ladder, with tests for each branch (including a day when 40 stocks fall together: one market note, no per-stock searches)
- [ ] Market alert page and note (at most one refresh per 3 hours)
- [ ] Refresh button and "more coverage" searches with caps (AGENTS.md rule 6)
- [ ] Done when: a 6% single-stock move gets its own note, a market-wide drop gets one shared note, and a 4th refresh in a day is refused

## Day 6 — Deploy

- [ ] **Data-licensing gate (must pass before deploying):** `docs/data-licensing.md` records one of:
  - written permission from the price provider for this use, or
  - a paid provider whose terms allow display, confirmed in writing, or
  - the fallback: detect moves from news headlines instead of a price feed (build it first).
  Until one is ticked, do not deploy publicly.
- [ ] Neon database; switch `DATABASE_URL`
- [ ] GitHub Actions: daily job after US close, Monday/Thursday summary, profile queue
- [ ] Streamlit Community Cloud deploy with secrets, `APP_ENV=prod`
- [ ] Google OAuth consent screen set to "In production"
- [ ] Done when: it runs without your laptop, and a friend can sign in

## Day 7 — Buffer and showcase

- [ ] Hand-check 20 AI notes against their sources
- [ ] Privacy note (email and outlet choices stored; nothing else) and "Delete my account" button
- [ ] Footer disclaimer, Brave credit line, TradingView links on widgets
- [ ] README: what it does, architecture, the attribution ladder, cost caps, why prices come from TradingView widgets; 1–2 minute demo video at the top
- [ ] Done when: you'd send the link to an employer

## Later

- Risk tab: VaR and beta from a price CSV the user uploads, or their own free Tiingo key (no data is redistributed)
- Foreign companies listed in the US (ADRs such as ASML and TSMC; verify each files with the SEC), tagged by region; then home-listed European and Asian stocks (each country needs its own filing source)
- Theme tags per stock (China exposure, oil, rates, AI) for shared notes
- Risk-factor comparison between this year's and last year's 10-K
- NiceGUI front end

## Session log

<!-- Each session: date, tool (Claude Code / Codex), what was done, what's next. -->

- 2026-11-22, Claude Code: Day 0 setup done (tools, repo pushed to GitHub, placeholder app, data-licensing doc). Accounts and the Alpha Vantage email are still open.
- Next: owner creates Anthropic, Brave and Google Cloud accounts and sends the Alpha Vantage email; then Day 1.
