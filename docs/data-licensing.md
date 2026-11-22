# Data licensing

Which data source the site uses, what its terms allow, and any written permission received.
**Do not deploy publicly until the Day 6 gate in PLAN.md is ticked** (AGENTS.md rule 13).

## Prices

We show prices only through TradingView widgets. The price provider is used only to compute
daily percent changes (stocks and SPY), stored in `daily_returns`.

| Provider | Terms summary | Permission status |
|---|---|---|
| yfinance | Personal use only. Local development only; blocked when `APP_ENV=prod`. | n/a (dev only) |
| Alpha Vantage | Free key is personal use. Written permission requested for a non-commercial public portfolio site. | Not yet asked |
| Tiingo (optional) | Asked for the same. | Not yet asked |

### Custom chart (dev only for now)

`ui/chart.py` draws our own chart from daily closing prices. While `APP_ENV=local` the data comes from yfinance (personal use, fetched live, in-memory cache, never stored). In prod `CHART_PROVIDER=none`, so the site shows TradingView widgets instead. To switch the custom chart on in prod we need a provider with display rights recorded here. Candidates to check: Alpha Vantage written permission for daily closes; a plan that explicitly covers display to users (e.g. Intrinio, Massive Business); Tiingo redistribution via sales.

### Emails sent / replies received

(Paste the date, who it was sent to, and the reply here.)

## News

| Source | Terms summary | Notes |
|---|---|---|
| Brave News Search API | Free monthly credit requires a credit line in the footer. Results must not be stored beyond transient use (< 1 hour in memory). We store only our own note plus the cited URL and outlet. | Day 3: check whether results can be restricted to named outlets (`site:`); record the answer here. |
| Finnhub | Free plan is personal use. **Not used.** | |
| Outlet RSS feeds | Fallback only. | Check each outlet's terms before use. |

## SEC EDGAR

Public data. Requests must send a `User-Agent` with a name and contact email and stay under 10 requests per second.

## TradingView

Free embed widgets. Keep the TradingView link on every widget.
