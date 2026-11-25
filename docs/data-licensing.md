# Data licensing

Which data source the site uses, what its terms allow, and any written permission received.
**Sharing price-provider figures requires the Day 6 gate in PLAN.md** (AGENTS.md rule 13). Visitor quotes come from TradingView.

## Prices

We show prices only through TradingView widgets. The price provider is used only to compute
daily percent changes (stocks and SPY), stored in `daily_returns`.

| Provider | Terms summary | Permission status |
|---|---|---|
| yfinance | Personal use only. Local development only; blocked when `APP_ENV=prod`. | n/a (dev only) |
| Alpha Vantage | Free key is personal use. Written permission requested for a small, private (link-only), non-commercial portfolio site. | Asked 2026-11-23 (see below) |
| Tiingo | Free plan is internal use only. Redistribution licence requested. | Asked 2026-11-23 (see below) |
| Marketstack | Basic ($9.99/month): "Commercial Use", EOD data, 10,000 requests a month. Daily job provider (`PRICE_PROVIDER=marketstack`). | See below; written confirmation of public display requested |

### Marketstack Basic (researched 2026-11-25)

Chosen by the owner as the only option at about $10/month that may cover public display. What the pages say:

- Pricing page: Free is "Non-Commercial Use"; Basic ($9.99/month, $8.99 billed yearly) and up are "Commercial Use".
  No page states a display or redistribution restriction, and none states attribution.
- Governing terms: the apilayer Master SaaS Subscription Agreement (marketstack.com/terms redirects there). It grants a
  "limited, non-exclusive and non-transferable right and license ... to access and use the Licensed Material" under the
  restrictions of the plan bought. It has no clause on displaying data to third parties.
- FAQ: US exchange data "is licensed and sourced from Tiingo, Inc." Each symbol in a request counts as one request.
- Not confirmed in writing yet. Ask Marketstack support to confirm that the Basic plan may show daily % changes
  (no prices) to visitors of a free, non-commercial site with a "Data by Marketstack" credit. Record the reply here.

Comparison (2026-11-25): Alpha Vantage, Twelve Data (free = "internal non-display usage"; display from $499/month),
FMP (display needs a separate agreement), EODHD, Massive/Polygon (display on Business plans), MarketData.app
(display only on Commercial, from $333/month) and Tiingo (redistribution from about $250/month) were all ruled out.
IEX historical files are no longer downloadable.

How we use it: the daily job fetches end-of-day adjusted closes and stores only daily % changes (`daily_returns`).
Requests are sized to one page each and only missing days are fetched (about 183 a weekday, 366 for a full backfill).

### Tiingo Starter watchlist aggregate

Tiingo Sales confirmed that the free public demo may show a single equal-weight change across
multiple stocks, with “Data sourced by Tiingo” linked to Tiingo. The 24x5 feed is refreshed at
15-minute intervals on demand. Tiingo prices and single-stock returns are private to the backend
and never written to durable storage. Single-stock watchlists show a fallback. The existing
daily-return job does not use this feed. Tiingo also allows internal closing-news triggers if
resulting summaries omit raw Tiingo prices and exact moves. The closing-news job uses official
end-of-day closes to select subjects in memory and persists only sourced descriptions and links.

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
- Websites and apps that show data need a redistribution licence ("flat rate", price not listed): email sales@tiingo.com (confirmed in
  the pricing page's own text: "to redistribute data, please contact sales@tiingo.com") with the
  use case, website link, and whether a start-up (<5 employees) or enterprise. Attribution required: "Tiingo must be
  clearly attributed as the data source."

**What we show in prod** (to describe accurately in the requests): daily percent changes of ~183 US-listed symbols (100 US stocks, 50 European and Asian companies' US listings,
32 index funds/ETFs, SPY), returns over fixed ranges (1D to 5Y), volatility, beta, largest drop, best and worst day,
and alerts on big moves. No prices, OHLC, or charts from the provider (prices and charts are TradingView widgets).
We store only daily percent changes. Provider figures are available to the owner. The site is noindex, with no ads or payments.

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
- **Logos** are Wikimedia Commons symbol files curated in `config/logo_icons.csv` (symbols only, no wordmarks;
  companies without a clean symbol show a monogram tile), shown as Commons thumbnails. Most company logos on
  Commons are public-domain text logos; each file page states its licence and they remain trademarks of their
  owners (used only to identify the company). The stock page's sources list links the logo's file page.
- Requests send a generic User-Agent ("StockTracker/0.1 (personal portfolio project)"), no personal data.

The international catalog uses TradingView embeds on exchanges listed in their widget coverage and direct symbol links
elsewhere. In particular, the widget coverage list does not include KRX, even though TradingView hosts Korean stock pages.
International catalog entries incur no server-side quote, SEC, or AI profile requests.
See [European widget coverage](https://www.tradingview.com/widget-docs/markets/europe/) and
[Asia-Pacific widget coverage](https://www.tradingview.com/widget-docs/markets/asia-pacific/).
