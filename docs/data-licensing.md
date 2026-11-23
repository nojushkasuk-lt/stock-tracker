# Data licensing

Which data source the site uses, what its terms allow, and any written permission received.
**Do not deploy publicly until the Day 6 gate in PLAN.md is ticked** (AGENTS.md rule 13).

## Prices

We show prices only through TradingView widgets. The price provider is used only to compute
daily percent changes (stocks and SPY), stored in `daily_returns`.

| Provider | Terms summary | Permission status |
|---|---|---|
| yfinance | Personal use only. Local development only; blocked when `APP_ENV=prod`. | n/a (dev only) |
| Alpha Vantage | Free key is personal use. Written permission requested for a non-commercial public portfolio site. | Asked 2026-11-23 (see below) |
| Tiingo | Free plan is internal use only. Redistribution licence requested. | Asked 2026-11-23 (see below) |

### What the terms say (read 2026-11-23)

**Alpha Vantage** (Terms of Service PDF; support and premium pages)
- Licence is "for personal, non-commercial use, unless you and Alpha Vantage have agreed otherwise in writing" (ToS 2a).
- "Commercial use" includes any purpose "that goes beyond investment analysis, research, testing, monitoring, and any
  other activities that are private and individual in nature" (2a.i). Showing data to other people (employers) is not
  private and individual, so we need their written agreement. Contact for this: premium@alphavantage.co (ToS 2).
- Free key: 25 requests per day, "and unlimited API requests for verified open-source or educational projects"
  (support page). Our repo is public, so we ask to be verified as open source. 25/day is not enough for ~183 symbols.
- Cheapest premium plan $49.99/month (75 requests/minute); the pages do not say premium plans allow display to others.
- No attribution requirement stated; no wording on derived data (percent changes).

**Tiingo** (Terms of Use, effective 2022-01-16, last updated 2026-11-05; pricing, overview, developer pages)
- Starter (free) and Power ($30/month) are "Internal Use Only": "you may only use the data for your own personal use and
  you may not display or share the data with another person or organization."
- Starter may not store Tiingo data or Derived Products persistently (ToS 1.6a): our `daily_returns` table would break this.
- Derived Products (ToS 1.6c): percentage returns/changes may be allowed when "their scope, granularity, and
  presentation do not permit the underlying Tiingo Data to be reconstructed"; series rebased or indexed to 100 are not.
  A full daily return series can be rebased, so our use needs their approval either way.
- Websites and apps that show data need a redistribution licence ("flat rate", price not listed): email sales with the
  use case, website link, and whether a start-up (<5 employees) or enterprise. Attribution required: "Tiingo must be
  clearly attributed as the data source."

**What we show in prod** (to describe accurately in the requests): daily percent changes of ~183 US-listed symbols (100 US stocks, 50 European and Asian companies' US listings,
32 index funds/ETFs, SPY), returns over fixed ranges (1D to 5Y), volatility, beta, largest drop, best and worst day,
and alerts on big moves. No prices, OHLC, or charts from the provider (prices and charts are TradingView widgets).
We store only daily percent changes. Access is private (shared links), noindex, no ads, no payments.

### Custom chart (dev only for now)

`ui/chart.py` draws our own chart from daily closing prices. While `APP_ENV=local` the data comes from yfinance (personal use, fetched live, in-memory cache, never stored). In prod `CHART_PROVIDER=none`, so the site shows TradingView widgets instead. To switch the custom chart on in prod we need a provider with display rights recorded here. Candidates to check: Alpha Vantage written permission for daily closes; a plan that explicitly covers display to users (e.g. Intrinio, Massive Business); Tiingo redistribution via sales.

### Emails sent / replies received

(Paste the date, who it was sent to, and the reply here.)

## News

| Source | Terms summary | Notes |
|---|---|---|
| Brave News Search API | Free monthly credit requires a credit line in the footer. Results must not be stored beyond transient use (< 1 hour in memory). We store only our own note plus the cited URL and outlet. | `site:` confirmed with a live key (2026-11-22), including `(site:a OR site:b)`. We restrict each query to the chosen outlets and also filter by domain on our side. Coverage gaps: Brave returned no news for wsj.com. Search plan includes news; limits seen in headers: 50 requests/second. |
| Finnhub | Free plan is personal use. **Not used.** | |
| Outlet RSS feeds | Fallback only. | Check each outlet's terms before use. |

## SEC EDGAR

Public data. Requests must send a `User-Agent` with a name and contact email and stay under 10 requests per second.

## TradingView

Free embed widgets. Keep the TradingView link on every widget.

## Wikidata (company key facts) and Wikimedia Commons (logos)

Added 2026-11-23 (owner approved Wikidata / Wikipedia as sources for company facts and history).

- **Wikidata** structured data is CC0 (public domain): CEO, headquarters, founding year, employees, website,
  Wikipedia link, logo file name. Matched by SEC CIK (P5531), falling back to the ticker on a US exchange.
  Fetched weekly by `python -m jobs.facts` into `company_facts`. Shown with "From Wikidata, checked <date>".
  Facts can be edited by anyone; spot-checked 2026-11-23: Apple CEO John Ternus (from Sep 1, 2026) and NVIDIA
  interim CEO Colette Kress (from Nov 12, 2026) both match the companies' own announcements.
- **Logos** are Wikimedia Commons files (`logo_url`), shown as Commons thumbnails. Most company logos on
  Commons are public-domain text logos; each file page states its licence and they remain trademarks of their
  owners (used only to identify the company). The stock page's sources list links the logo's file page.
- Requests send a generic User-Agent ("StockTracker/0.1 (personal portfolio project)"), no personal data.
