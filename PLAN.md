# PLAN.md — Stock Tracker

## Decisions

- Public by URL, non-commercial, and noindex. Anyone can open the read-only demo or sign in with Google. Visitors get TradingView quotes, while the third-party provider figures stay owner-only until the Day 6 licensing gate is ticked.
- Users pick up to 15 stocks from the 100 largest US companies plus 25 European and 25 Asian SEC-registered foreign filers (`universe` table, `region` column; owner decision 2026-11-23). Non-SEC companies (ESEF, DART, EDINET) later.
- Display: TradingView free widgets for charts, quotes, heatmap and economic calendar. Fundamentals and ratios from EDGAR. No P/E, VaR or beta in v1 (P/E needs a price; the TradingView symbol-info widget shows it).
- Moves: a daily percent change of 5% or more triggers an alert. The app decides market vs industry vs stock before searching anything (AGENTS.md rule 14).
- News: link-based. Live Brave search, filtered to the outlets each user picks; the AI writes a short note and ranks links. Headline-only wording for paywalled outlets.
- Models: Haiku 5.5 for notes and the Monday/Thursday summary. Sonnet 5.5 for profile updates when a company files a 10-Q, 10-K or earnings 8-K.
- Streamlit first; UI kept thin so it can move to NiceGUI later.
- Budget: AI hard stop at $8/month (prepaid credit, auto top-up off); live searches capped at 900/month (Brave's free monthly credit).
- Charts (owner decision 2026-11-22): build our own minimalist chart (Trading 212 / Trade Republic style) on dev-only yfinance data now; in prod it falls back to TradingView widgets until a licensed price source is confirmed. Alpha Vantage email to be rewritten to ask for permission to display daily closing prices (later).
- Price source: undecided. Free tiers are personal-use. Plan: ask Alpha Vantage (open-source/educational key) for written permission. Development uses yfinance locally only. Do not deploy publicly before the Day 6 gate.

## Day 0 — Setup (evening)

- [x] Accounts: GitHub, Anthropic Console (prepaid credit, auto top-up off), Brave Search API (card needed; keep spending cap), Google Cloud (OAuth client). No Finnhub.
- [ ] Email Alpha Vantage (premium@alphavantage.co) asking for written permission to use their API for a non-commercial public portfolio site (public GitHub repo, 100 US stocks, daily percent changes only, charts via TradingView). Optional: the same to Tiingo sales. Save replies in `docs/data-licensing.md`.
- [x] Install Python 3.12, Git, VS Code, Claude Code, Codex
- [x] Repo with AGENTS.md, PLAN.md, schema.sql, `.gitignore` (including `.env`, `.venv`, `*.db`), `.env.example`, `requirements.txt`, `docs/data-licensing.md`
- [x] `app.py` shows a placeholder page with `streamlit run app.py`

## Day 1 — Data foundation and display

- [x] `models.py` from schema.sql; `db.py`; tables created in SQLite
- [ ] `config/universe.csv`: the 100 largest US companies with CIK, name, industry (own labels or EDGAR SIC codes, not GICS), rank; top 20 flagged `is_demo`. I (the owner) verify the list by hand.
- [x] `PriceProvider` interface and `yfinance_dev.py` (blocked when `APP_ENV=prod`); `daily_returns` filled for the universe and SPY
- [x] Automatic universe refresh: a scheduled job keeps `config/universe.csv` / the `universe` table in line with the market-cap ranking (entries, exits, demo top 20). Design agreed with the owner first; users who follow an exiting stock keep it (see session log 2026-11-22).
- [x] `ui/tradingview.py`: chart and symbol-info widgets; stock page shows them
- [ ] Done when: picking a demo ticker shows its chart and quote

- [x] Custom minimalist chart on dev-only data (`ui/chart.py`, `tracker/data/charts.py`); TradingView widgets as the prod fallback
- [ ] Owner picks the chart look / confirms the new page (Trading 212 / Trade Republic style)

## Day 2 — Fundamentals

- [x] EDGAR XBRL companyfacts → `fundamentals`
- [x] Ratios: operating margin, net margin, net debt/EBITDA, revenue growth (YoY), diluted EPS
- [x] Metric cards and a Plotly chart of revenue and margins on the stock page
- [x] Tests for every ratio
- [ ] Done when: ratios match a trusted source for 3 companies

## Day 3 — News links and filings

- [x] `news.py`: Brave live news search with a transient cache (under 1 hour) and no storage of results
- [x] **Check whether Brave can restrict results to named outlets** (e.g. a `site:` operator). If not, fall back to each outlet's RSS feed matched by company name. Record the answer in `docs/data-licensing.md`.
- [x] `config/outlets.toml` (Bloomberg, WSJ, NYT, FT, Reuters, CNBC, ...)
- [x] EDGAR submissions check → new 10-Q / 10-K / 8-K rows in `filings`
- [x] Stock page: "More coverage" button with live, outlet-filtered links
- [x] Market page: TradingView heatmap and economic calendar widgets; static Fed and Treasury links
- [x] Done when: a stock returns links from the chosen outlets only, nothing is stored, and a new filing is detected

## Day 4 — AI layer

- [x] `llm.py`: one wrapper, budget check, cost log, model names from config
- [x] Prompts in `ai/prompts/`; pydantic output models; source-ID validation; cautious wording for headline-only notes
- [x] Profile update from a filing (Sonnet); short stock / industry / market notes and link ranking (Haiku)
- [x] Cache outputs by input hash
- [x] Dev-only model test (not deployed): 20 recent real moves through Haiku (owner decision 2026-11-23: Haiku only, no DeepSeek / GLM). Record: relevant links ranked first yes/no, any unsupported claim, any claim stated as certain when only a headline was seen. Results in docs/model-test.md.
- [x] Done when: a profile shows only claims with valid sources and a note never states a cause as fact from headlines alone

## Day 5 — Users, moves and the ladder

- [x] Google sign-in (`st.login`), `users`, `user_watchlist`, `user_outlets`; setup page to pick stocks (max 15) and outlets. Owner verified Google sign-in locally 2026-11-23 (OAuth client in Testing mode; `.streamlit/secrets.toml`, gitignored).
- [x] Demo mode: read-only, no AI calls, no searches
- [x] `moves.py`: detection and the market → industry → stock ladder, with tests for each branch (including a day when 40 stocks fall together: one market note, no per-stock searches)
- [x] Market alert page and note (at most one refresh per 3 hours)
- [x] Refresh button and "more coverage" searches with caps (AGENTS.md rule 6)
- [x] Done when: a 6% single-stock move gets its own note, a market-wide drop gets one shared note, and a 4th refresh in a day is refused

## UI design pass (after Day 5, before Day 6)

- [ ] Full visual design with all content in place: layout, cards, typography, metric tiles, AI notes, market page, sign-in flow. Streamlit theme and CSS first; NiceGUI only if Streamlit cannot do it.
- [ ] Rewrite the Alpha Vantage email to ask for permission to display daily closing prices (and check display-licensed plans such as Intrinio, Massive Business, Tiingo redistribution) so the custom chart can go live in prod.

## Day 6 — Deploy

- [ ] **Data-licensing gate (must pass before deploying):** `docs/data-licensing.md` records one of:
  - written permission from the price provider for this use, or
  - a paid provider whose terms allow display, confirmed in writing, or
  - the fallback: detect moves from news headlines instead of a price feed (build it first).
  Until one is ticked, public visitors get quotes and price changes through TradingView.
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

- **Live mode (owner decision 2026-11-22):** second-by-second / minute price updates, live ticker and intraday moves, fed by a personal-use source (e.g. Finnhub WebSocket or Alpaca IEX, terms checked first). Only when running locally or for the owner's own account; public visitors keep the licensed version. Good for the demo video and interviews.
- **App structure and features the owner wants:** tabs (stocks, market, news), profile and settings, notifications, portfolio view, stock search, a market-wide news tab, ETFs. Plan these into the UI design pass.

- Risk tab: VaR and beta from a price CSV the user uploads, or their own free Tiingo key (no data is redistributed)
- Foreign companies listed in the US (ADRs such as ASML and TSMC; verify each files with the SEC), tagged by region; then home-listed European and Asian stocks (each country needs its own filing source)
- Theme tags per stock (China exposure, oil, rates, AI) for shared notes
- Risk-factor comparison between this year's and last year's 10-K
- NiceGUI front end

## Session log

<!-- Each session: date, tool (Claude Code / Codex), what was done, what's next. -->

- 2026-11-22, Claude Code: Day 0 setup done (tools, repo pushed to GitHub, placeholder app, data-licensing doc). Accounts and the Alpha Vantage email are still open.
- Next: owner creates Anthropic, Brave and Google Cloud accounts and sends the Alpha Vantage email; then Day 1.
- 2026-11-22, Claude Code: Day 1 so far: models/db/config, universe.csv (sourced, owner still to verify), universe loader, PriceProvider + yfinance_dev (prod guard), jobs/daily.py fills daily_returns (101 tickers, 5y). Owner wants the universe to update automatically; needs a market-cap source decision (see AGENTS.md rule 13).
- Next: decide the universe-refresh source, then ui/tradingview.py and the stock page.
- 2026-11-22, Claude Code: universe auto-refresh built (jobs/universe.py, buffer of 110, soft exits via `active`, candidates.csv ranks 101-200, tests). Open: Yahoo market caps count only the listed share class, so BX, CVNA, IBKR rank too low and would exit wrongly. Needs an owner decision (pins/overrides vs total-cap source). Not scheduled yet (Day 6); no IPO discovery yet.
- 2026-11-22, Claude Code: universe refresh finished (option B): rule = top 100 by provider market cap, weekly SEC new-listing check (domestic filers only), pins.csv escape hatch. Not scheduled until Day 6. Alpha Vantage email still to send (owner, later); prod caps then come from that provider.
- Next: ui/tradingview.py and the stock page (last Day 1 task).
- 2026-11-22, Claude Code: Day 1 stock page built (tracker/services.py, ui/tradingview.py, demo picker for the top 20). Widgets verified rendering with real data in headless Chrome; the in-app live data load is for the owner to eyeball (`streamlit run app.py`).
- Next: owner verifies universe.csv and the demo page (closes Day 1), then Day 2: EDGAR fundamentals.
- 2026-11-22, Claude Code: custom Trading 212-style chart built (Lightweight Charts, closing prices, 1M/1Y/5Y/Max chips, hover shows price and date), dev data only; prod falls back to TradingView widgets. Rendered standalone with real Apple data. In-app screenshots were flaky in headless Chrome, owner to eyeball.
- Next: owner reviews the page; then Day 2 (EDGAR fundamentals). Design pass and the licensing email come later.
- 2026-11-22, Claude Code: Day 2 built: EDGAR companyfacts -> fundamentals (10 tags merged by concept), TTM ratios, metric cards, revenue/margin chart, predecessor mapping (XOM), 70 tests. Net debt/EBITDA available for 51 of the 85 companies where it applies; n/a shown with a reason otherwise. Checked against stockanalysis.com for AAPL, KO, PG: revenue, net margin, EPS match exactly; operating margin/EBITDA match for AAPL only (KO, PG: source adds back one-offs); net debt defined more conservatively. Details in docs/metrics.md.
- Next: owner decides if the definitions are acceptable (closes Day 2 "done when"); then Day 3 (news links and filings).
- 2026-11-22, Claude Code: Day 3 built: filings detection (baseline + 400-day window; earnings 8-K = item 2.02; new 10-Q/10-K refetches figures), Brave news module (in-memory cache < 1h, monthly cap in usage_log, outlet filter, nothing stored), outlets.toml, page split into tabs (Stocks: Financials / Coverage / Filings; Market: heatmap, economic calendar, official sources). Found and fixed a bug where old filings were re-queued on the second check. 89 tests.
- Next: owner adds BRAVE_SEARCH_API_KEY to .env; then verify live search and the site: operator, and tick the remaining Day 3 boxes. Then Day 4 (AI layer, needs Anthropic credit).
- 2026-11-22, Claude Code: Brave key verified live. `site:` works and OR-combines (Reuters, CNBC, Yahoo Finance, Bloomberg return results; Brave returns no WSJ news at all). Queries now restrict to the chosen outlets, with at most 4 links per outlet. 91 tests.
- Next: Day 4 (AI layer). Owner: Anthropic prepaid credit (auto top-up off) before the first real model call.
- 2026-11-23, Claude Code: Haiku 5.5 vs Sonnet 5.5 compared on the same notes and profile (docs/model-choice.md): equal on notes, Sonnet slightly better on profiles, so the split stays. Built llm.py (budget stop incl. worst case of the next call, 100k prompt cap via count_tokens, cost log, refusals logged) and citations.py + prompts + output schemas (unknown source IDs, invented numbers, unhedged headline claims and unsupported "beat" dropped). 118 tests; no real API call yet (key empty).
- Next: notes/profile generation with ai_outputs and the input-hash cache. Owner: put ANTHROPIC_API_KEY in .env (prepaid credit, auto top-up off) for the first live call.
- 2026-11-23, Claude Code: first live calls OK (key in .env). Built ai_outputs store with input-hash cache, move-note generation (shared market/industry keys, ranked links stored as id/url/outlet), filing section extraction (10-K Items 1/1A/7, 10-Q MD&A, 8-K EX-99), profile generation and queue (`python -m jobs.profiles`: covered stocks only, newest filing per company, stops at budget). Real Costco 10-K profile: $0.07, nothing dropped. 138 tests. Live spend so far about $0.15.
- Next: Day 4 model test (20 real moves; DeepSeek / GLM need accounts) and "done when" check; notes are wired to moves on Day 5. Profiles not yet in the UI or scheduled.
- 2026-11-23, Claude Code: Day 4 model test done (docs/model-test.md): 20 real moves, no unsupported claims, no causes stated as fact from headlines, relevant links first. Fixed: earnings exhibit lookup by EX-99 type (TJX), news-after-the-move rule, no talk about inputs, 60-word summaries. 140 tests; live spend about $0.19, about 47 Brave searches.
- 2026-11-23, Claude Code: Profile tab on the stock page (services.get_profile, source links per point, Markdown/$ escaped). Apple profile generated for the demo ($0.06). Day 4 done. 143 tests; live spend about $0.25.
- Next: Day 5 (sign-in, watchlist, moves.py ladder, market page note, caps). Profiles are not scheduled yet (Day 6 Actions); run `python -m jobs.profiles` by hand.
- 2026-11-23, Claude Code: Day 5 built: moves.py ladder (tests for every branch and the 40-stock day), daily job writes market / industry / stock notes with earnings releases filed before the close, rechecks (`jobs.daily --recheck`), market note at most every 3 hours; accounts.py (watchlist max 15, outlets, 3 refreshes/day, 300/month, 6-hour shared refresh, 10 coverage searches/day); page: sign-in (Google or local dev box), watchlist and outlet settings, move-note card, Refresh now, market alert with the shared note. Live: Nov 20 sell-off, 10 demo moves -> 7 notes. All timestamps now UTC. 190 tests; spend about $0.25.
- 2026-11-23: owner verified Google sign-in locally. Day 5 complete.
- Next: UI design pass with the owner's list of design and content changes, then Day 6.

## Redesign (owner decisions, 2026-11-23)

- Frontend: replace Streamlit with FastAPI + server-rendered pages + Tailwind; own domain on a small host (~$5–7/month). `tracker/` logic stays; only the page layer changes.
- Sign-in: Google only, on a separate start page with "Explore the demo".
- Company history: Wikipedia allowed as a cited source, for history only. The About section is one paragraph: a few historical facts that explain how the company reached its position, plus its main selling points. Not a history lesson.
- Look: minimalist but sophisticated, dark blue / blue-gray palette. Mockups: https://claude.ai/artifact/MrZqaUub8gP6irMyBEetQo (A Midnight, B Harbor, C Slate). Owner picks one.
- Then, in order: new site on the existing services; richer content (About, sections, risk metrics from daily returns, logos); ETFs; international (20-F filers, then EU ESEF, then Korea DART, Japan last); deploy on the domain (licensing gate still applies).
- [x] Owner picks a design direction: A · Midnight (2026-11-23). Changes asked: range tabs show that range's performance (1D default), plainer start-page wording, a Coverage section with key articles from the chosen outlets, owner credit in the footer.
- [ ] Owner picks the host and buys the domain
- [x] New site, first slice (`web/`): start page (Google / demo), portfolio, stock page (performance ranges, chart, latest move, About, profile tabs, coverage, filings, numbered sources, key facts, valuation widget, growth/balance/risk metrics), market, settings. Tested (`tests/test_web.py`).
- [ ] Owner adds `http://localhost:8000/auth/callback` to the Google OAuth client's redirect URIs
- [ ] Portfolio "since your start date" (start date per stock; local only until a display-licensed price source)
- [x] Wikidata key facts (CEO, HQ, founded, employees, website) and Commons logos: 102 of 103 companies, 99 logos (`jobs.facts`; schedule weekly on Day 6)
- [x] Owner feedback fixed: one chart (1D–MAX locally; TradingView chart restyled in prod), own valuation card instead of the TradingView widget, demo visitors can sign in
- [x] About paragraph from Wikipedia (history) + filings (selling points); profile v2 with titled points, latest report, what to watch (AAPL, NVDA generated)
- [x] Markets: 32 funds (US, international, bonds, commodities, sectors), fund pages, followed markets
- [x] Settings in sections; first sign-in setup (3+ stocks, markets, outlets, alerts); 36 outlets in groups
- [x] Alerts (bell, inbox, per-user threshold) and email alerts via the site's Gmail account (test email sent)
- [x] News page; private access by shared links (`ACCESS_MODE=link`, `/admin/links`)
- [x] First profiles for 99 of 100 stocks via the Batch API: top 30 Sonnet, rest Haiku ($1.80); followed Haiku stocks upgrade to Sonnet nightly (ANT: no filing yet)
- [ ] Portfolio since-start performance and card sparklines; ⌘K search
- [x] Day 6 hosting: Google Cloud Run (free tier, europe-west1) + Neon (Frankfurt), link-only. Price-provider figures owner-only (PRICE_DATA_DISPLAY=owner) until the licensing gate is ticked
- [ ] Retire the Streamlit app once the new site covers the revenue/margin chart
- 2026-11-23, Claude Code: redesign decided (Midnight, FastAPI, Google only, Wikipedia for history); first slice of the new site built on the existing services, with range performance and risk stats from daily returns. 203 tests.
- Next: owner adds the new redirect URI; then start dates and since-start performance, About from Wikipedia/Wikidata, logos, ETFs, international.
- 2026-11-23 (2), Claude Code: deeper profiles, markets and fund pages, sectioned settings, setup steps, alerts with email, news page, shared-link access. 235 tests. Desktop is iCloud-offloaded: venv now at ~/.venvs/stock-tracker.
- Next: owner confirms Batch profile run; since-start portfolio; then Day 6 deploy on Render Starter.
- 2026-11-23 (3), Claude Code: Batch API profiles for every stock, top-bar search and the hidden-element fix, Cloud Run container, Neon support, Actions workflows (not pushed). 244 tests.
- Next: owner decides the price-data licensing route (Day 6 gate); owner creates Neon + Google Cloud billing; then deploy.
- 2026-11-23 (4), Claude Code: Europe and Asia (25 + 25 SEC foreign filers): 20-F/6-K filings, IFRS and local-currency figures, Sonnet profiles for all 50 ($3.07). Deploy script ready; gcloud installed. 250 tests.
- Next: owner turns on Google Cloud billing, signs in to gcloud, creates Neon; then copy data and deploy link-only. Quarterly 6-K press releases (TSMC, Alibaba) are not yet detected as profile triggers.
- 2026-11-23 (5), Claude Code: deployed to Cloud Run + Neon (link-only); provider figures owner-only so share links are safe now. 252 tests.
- Next: push to GitHub; scheduled jobs (JOBS_ENABLED) once a licensed price provider is chosen; owner sends the provider emails.
- [x] Add 50 international listings to browsing, search and watchlists. Use TradingView for daily changes in embeds where supported and via symbol links elsewhere. Keep the new listings outside paid quote and profile jobs.
- 2026-11-23, Codex: added a TradingView portfolio quote strip and a 50-stock international catalog, including Samsung and European luxury and auto makers.
- Next: deploy to Cloud Run and check real widget rendering from a shared link.

- [x] Configure Cloud Run deployments for a public demo and Google sign-in, with TradingView for visitor quotes.
- Codex: verified public access and Google callback handling locally. Applying the Cloud Run environment change is pending network access.

- [x] Include all active international stocks in the directory and demo search, restore saved logo display, and add Commons logo fallbacks.
- Codex: audited the active and reserve lists and clarified that move-note refreshes use stored closing returns. Cloud Run deployment remains pending.
