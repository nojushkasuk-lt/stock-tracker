"""Stock Tracker website (FastAPI + server-rendered Jinja pages).

Display only, like the Streamlit app it replaces (AGENTS.md rule 1): every piece of data comes from
tracker.services, widgets come from ui.tradingview. Jinja autoescapes all text, including model output.

Run locally:  uvicorn web.main:app --reload   (then open http://localhost:8000)
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from tracker import config, services
from ui import tradingview as tv
from web import access, auth, views

HERE = Path(__file__).resolve().parent

@asynccontextmanager
async def lifespan(app: FastAPI):
    from starlette.concurrency import run_in_threadpool
    await run_in_threadpool(services.register_global_stocks)
    yield


app = FastAPI(lifespan=lifespan, title="Stock Tracker", docs_url=None, redoc_url=None, openapi_url=None)


def _closed(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "closed.html", {"me": viewer(request), "google": auth.configured()}, status_code=403)


access.install(app, _closed)  # before the session middleware, so the gate runs inside it
app.add_middleware(SessionMiddleware, secret_key=config.SESSION_SECRET or "dev-only-not-secret",
                   same_site="lax", https_only=config.APP_ENV == "prod", max_age=60 * 60 * 24 * 30)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
views.register_filters(templates.env)
templates.env.globals.update(credit=config.OWNER_CREDIT)
auth.register(app)


def viewer(request: Request) -> views.Viewer:
    s = request.session
    services.set_viewer(s.get("email"))  # price-provider figures are shown to the owner only until licensed
    return views.Viewer(email=s.get("email"), name=s.get("name"), demo=bool(s.get("demo")) and not s.get("email"))


def page(request: Request, name: str, **ctx) -> HTMLResponse:
    me = viewer(request)
    ctx.setdefault("flash", request.session.pop("flash", None))
    ctx.setdefault("unread", services.unread_alerts(me.email) if me.email else 0)
    return templates.TemplateResponse(request, name, {"me": me, **ctx})


def require_viewer(request: Request) -> views.Viewer:
    me = viewer(request)
    if not (me.email or me.demo):
        raise views.GoStart()
    return me


@app.exception_handler(views.GoStart)
async def _go_start(request: Request, exc: views.GoStart):
    return RedirectResponse("/", status_code=303)


# ---- start, demo ----------------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def start(request: Request):
    me = viewer(request)
    if me.email:
        return RedirectResponse(services.home_path(me.email), status_code=303)
    # Demo visitors see the start page too, so they can sign in from the demo.
    return page(request, "start.html", google=auth.configured(), dev_login=auth.dev_login_allowed())


@app.get("/demo")
def demo(request: Request):
    access_token = request.session.get("access")  # keep a shared-link pass when entering the demo
    request.session.clear()
    request.session["demo"] = True
    if access_token:
        request.session["access"] = access_token
    return RedirectResponse("/portfolio", status_code=303)


# ---- portfolio ------------------------------------------------------------------------------------

@app.get("/portfolio", response_class=HTMLResponse)
def portfolio(request: Request):
    me = require_viewer(request)
    stocks = services.get_watchlist(me.email) if me.email else services.get_demo_stocks()
    moves = services.get_last_moves([s.ticker for s in stocks])
    cards = [views.stock_card(s, moves.get(s.ticker)) for s in stocks]
    pairs = [(s, n) for s in stocks if (n := services.get_move_note(s.ticker, me.email))]
    note_stock, note = views.latest_note(pairs)
    quote_symbols = [c["s"].tv_symbol for c in cards if c["day"] is None and c["s"].quote_embeddable]
    return page(request, "portfolio.html", cards=cards, market=services.get_market_status(me.email),
                summary=views.day_summary(cards), note=note, note_stock=note_stock,
                exposure=views.exposure_breakdown(stocks),
                market_quote=tv.quote_html("AMEX:SPY"),
                ticker_tape=tv.ticker_tape_html(quote_symbols) if quote_symbols else None,
                max_stocks=services.watchlist_max(), nav="portfolio")


@app.get("/search.json")
def search_index(request: Request):
    """Stocks and funds the viewer can open from the top-bar search."""
    from fastapi.responses import JSONResponse

    me = require_viewer(request)
    stocks = (services.get_demo_stocks() + services.get_international_stocks()
              if me.demo else services.get_followable_stocks(me.email))
    items = [{"t": s.ticker, "n": s.name, "k": s.industry, "u": f"/stock/{s.ticker}"} for s in stocks]
    items += [{"t": f.ticker, "n": f.name, "k": f.group, "u": f"/etf/{f.ticker}"} for f in services.get_market_list()]
    return JSONResponse(items, headers={"Cache-Control": "private, max-age=300"})


@app.get("/international", response_class=HTMLResponse)
def international(request: Request):
    require_viewer(request)
    return page(request, "international.html", stocks=services.get_international_stocks(), nav="international")


# ---- stock page -----------------------------------------------------------------------------------

def _stock_or_404(me: views.Viewer, ticker: str):
    stock = services.get_stock(ticker)
    if stock is None:
        raise HTTPException(404, "Unknown stock")
    if me.demo and not stock.demo_visible:
        raise HTTPException(404, "Sign in to see this stock.")
    return stock


def _stock_page(request: Request, ticker: str, coverage=None):
    me = require_viewer(request)
    stock = _stock_or_404(me, ticker)
    following = bool(me.email) and stock.ticker in {s.ticker for s in services.get_watchlist(me.email)}
    perf = services.get_performance(stock.ticker)
    chart = None if stock.global_listing else services.get_price_chart(stock.ticker)  # None in prod: the TradingView chart is shown instead
    model = views.stock_model(
        stock=stock, perf=perf, profile=services.get_profile(stock.ticker),
        financials=services.get_financials(stock.ticker), note=services.get_move_note(stock.ticker, me.email),
        filings=services.get_recent_filings(stock.ticker), coverage=coverage,
        facts=services.get_key_facts(stock.ticker), chart=chart)
    chart_symbol = stock.chart_symbol
    return page(
        request, "stock.html", s=stock, m=model, following=following, nav="stocks",
        chart_widget=tv.chart_widget_html(chart_symbol, theme="dark", background=tv.MIDNIGHT_BG, grid=tv.MIDNIGHT_GRID)
        if not chart and chart_symbol else None,
        quote_widget=tv.quote_html(stock.tv_symbol) if not chart and not perf and stock.quote_embeddable else None,
        quote_url=tv.symbol_url(stock.tv_symbol) if stock.global_listing else None,
        chart_url=tv.chart_url(stock.tv_symbol), alternate_chart_label=stock.alternate_chart_label,
        chart_symbol=chart_symbol,
        can_refresh=bool(me.email and not stock.global_listing and services.price_data_visible(me.email)),
        refreshes_left=services.refreshes_left(me.email) if me.email else 0,
        coverage_on=services.coverage_enabled(me.email),
        searches_left=services.coverage_searches_left(me.email) if me.email else 0,
        outlets=views.outlet_names(services.get_outlet_choice(me.email) if me.email else set(), services.get_outlets()))


@app.get("/stock/{ticker}", response_class=HTMLResponse)
def stock(request: Request, ticker: str):
    return _stock_page(request, ticker)


@app.post("/stock/{ticker}/coverage", response_class=HTMLResponse)
def stock_coverage(request: Request, ticker: str):
    me = require_viewer(request)
    if not me.email:
        raise HTTPException(403, "Live coverage is for signed-in users.")
    domains = services.get_outlet_choice(me.email) or None
    return _stock_page(request, ticker, coverage=services.get_coverage(ticker, domains, me.email))


@app.post("/stock/{ticker}/refresh")
def stock_refresh(request: Request, ticker: str):
    me = require_viewer(request)
    if not me.email:
        raise HTTPException(403, "Refresh is for signed-in users.")
    stock = _stock_or_404(me, ticker)
    request.session["flash"] = services.request_refresh(me.email, stock.ticker)
    return RedirectResponse(f"/stock/{stock.ticker}", status_code=303)


# ---- market ---------------------------------------------------------------------------------------

@app.get("/market", response_class=HTMLResponse)
def market(request: Request):
    me = require_viewer(request)
    return page(request, "market.html", market=services.get_market_status(me.email), nav="market",
                groups=services.get_markets(me.email), followed=services.get_followed_markets(me.email),
                heatmap=tv.heatmap_html("dark"), calendar=tv.calendar_html("dark"))


@app.get("/etf/{ticker}", response_class=HTMLResponse)
def fund(request: Request, ticker: str):
    me = require_viewer(request)
    f = services.get_fund(ticker, me.email)
    if f is None:
        raise HTTPException(404, "Unknown fund")
    return page(request, "fund.html", f=f, chart=f.chart, nav="market",
                chart_url=tv.chart_url(f.tv_symbol),
                chart_widget=None if f.chart else tv.chart_widget_html(f.tv_symbol, theme="dark", background=tv.MIDNIGHT_BG, grid=tv.MIDNIGHT_GRID),
                quote_widget=None if f.chart or f.perf else tv.quote_html(f.tv_symbol))


@app.post("/etf/{ticker}/follow")
def fund_follow(request: Request, ticker: str):
    me = require_viewer(request)
    if not me.email:
        raise HTTPException(403, "Sign in to follow markets.")
    f = services.get_fund(ticker, me.email)
    if f is None:
        raise HTTPException(404, "Unknown fund")
    mine = services.get_followed_market_tickers(me.email)
    err = services.save_markets(me.email, [t for t in mine if t != f.ticker] if f.followed else mine + [f.ticker])
    request.session["flash"] = err or (f"Stopped following {f.ticker}." if f.followed else f"Following {f.ticker}.")
    return RedirectResponse(f"/etf/{f.ticker}", status_code=303)


# ---- settings (signed in only) ---------------------------------------------------------------------

def _settings_ctx(me: views.Viewer) -> dict:
    from datetime import date

    from tracker.accounts import MARKETS_MAX, THRESHOLDS
    from tracker.data import markets

    followed = services.get_watchlist(me.email)
    mine = {stock.ticker for stock in followed}
    stocks = followed + [stock for stock in services.get_followable_stocks(me.email) if stock.ticker not in mine]
    outlets = services.get_outlets()
    return dict(stocks=stocks, mine=mine, starts=services.get_start_dates(me.email), today=date.today().isoformat(),
                industries=sorted({s.industry for s in stocks}), regions=sorted({s.region for s in stocks}),
                market_list=services.get_market_list(), market_groups=markets.GROUPS, markets_max=MARKETS_MAX,
                my_markets=set(services.get_followed_market_tickers(me.email)),
                outlets=outlets, outlet_groups=list(dict.fromkeys(o.group for o in outlets)),
                my_outlets=services.get_outlet_choice(me.email), prefs=services.get_prefs(me.email), thresholds=THRESHOLDS,
                email_ready=config.email_ready(), max_stocks=services.watchlist_max(),
                refreshes_left=services.refreshes_left(me.email), searches_left=services.coverage_searches_left(me.email),
                is_owner=bool(config.OWNER_EMAIL) and me.email == config.OWNER_EMAIL)


@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request, error: str | None = None):
    me = require_viewer(request)
    if not me.email:
        return RedirectResponse("/", status_code=303)
    return page(request, "settings.html", nav="settings", error=error, **_settings_ctx(me))


def _start_dates(form, tickers: list[str]) -> dict:
    from datetime import date

    out = {}
    for t in tickers:
        raw = str(form.get(f"start_{t}") or "").strip()
        if raw:
            try:
                out[t] = date.fromisoformat(raw)
            except ValueError:
                pass
    return out


@app.post("/settings")
async def settings_save(request: Request):
    me = require_viewer(request)
    if not me.email:
        return RedirectResponse("/", status_code=303)
    form = await request.form()
    tickers = list(form.getlist("ticker"))
    err = (services.save_watchlist(me.email, tickers) or services.save_markets(me.email, list(form.getlist("market")))
           or services.save_prefs(me.email, **views.prefs_from_form(form, email_ready=config.email_ready())))
    if err:
        return settings(request, error=err)
    current = services.get_start_dates(me.email)
    for t, d in _start_dates(form, tickers).items():
        if current.get(t) != d.isoformat():
            err = services.set_start_date(me.email, t, d)
            if err:
                return settings(request, error=f"{t}: {err}")
    services.save_outlet_choice(me.email, list(form.getlist("outlet")))
    request.session["flash"] = "Settings saved."
    return RedirectResponse("/settings", status_code=303)


# ---- first sign-in setup ------------------------------------------------------------------------------

WELCOME_STEPS = ("stocks", "markets", "news", "alerts")


@app.get("/welcome", response_class=HTMLResponse)
def welcome(request: Request, step: str = "stocks", error: str | None = None):
    me = require_viewer(request)
    if not me.email:
        return RedirectResponse("/", status_code=303)
    if step not in WELCOME_STEPS:
        step = "stocks"
    return page(request, "welcome.html", step=step, steps=WELCOME_STEPS, index=WELCOME_STEPS.index(step), error=error,
                bare=True, **_settings_ctx(me))


@app.post("/welcome")
async def welcome_save(request: Request):
    me = require_viewer(request)
    if not me.email:
        return RedirectResponse("/", status_code=303)
    form = await request.form()
    step = str(form.get("step") or "stocks")
    skip = form.get("skip") == "1"
    err = None
    if step == "stocks":
        tickers = list(form.getlist("ticker"))
        err = (f"Pick at least {views.MIN_START_STOCKS} stocks to start." if len(set(tickers)) < views.MIN_START_STOCKS
               else services.save_watchlist(me.email, tickers))
    elif step == "markets" and not skip:
        err = services.save_markets(me.email, list(form.getlist("market")))
    elif step == "news":
        services.save_outlet_choice(me.email, [] if skip else list(form.getlist("outlet")))
    elif step == "alerts":
        err = services.save_prefs(me.email, **views.prefs_from_form(form, email_ready=config.email_ready(), alerts_only=True))
        if not err:
            services.finish_onboarding(me.email)
            request.session["flash"] = "You're set up. You can change any of this in Settings."
            return RedirectResponse("/portfolio", status_code=303)
    if err:
        return welcome(request, step=step, error=err)
    nxt = WELCOME_STEPS[min(WELCOME_STEPS.index(step) + 1, len(WELCOME_STEPS) - 1)] if step in WELCOME_STEPS else "stocks"
    return RedirectResponse(f"/welcome?step={nxt}", status_code=303)


# ---- alerts --------------------------------------------------------------------------------------------

@app.get("/alerts", response_class=HTMLResponse)
def alerts(request: Request):
    me = require_viewer(request)
    if not me.email:
        return RedirectResponse("/", status_code=303)
    items = services.get_alerts(me.email)
    resp = page(request, "alerts.html", items=items, nav="alerts")
    services.mark_alerts_read(me.email)  # after rendering, so new ones are highlighted this once
    return resp


# ---- news ----------------------------------------------------------------------------------------------

@app.get("/news", response_class=HTMLResponse)
def news(request: Request):
    me = require_viewer(request)
    return page(request, "news.html", nav="news", **views.news_model(services.get_news_page(me.email)))


@app.get("/earnings", response_class=HTMLResponse)
def earnings(request: Request):
    me = require_viewer(request)
    stocks = services.get_watchlist(me.email) if me.email else services.get_demo_stocks()
    return page(request, "earnings.html", nav="news", entries=services.get_earnings_calendar(stocks))


@app.post("/news/search", response_class=HTMLResponse)
def news_search(request: Request):
    me = require_viewer(request)
    if not me.email:
        raise HTTPException(403, "Live coverage is for signed-in users.")
    return page(request, "news.html", nav="news", **views.news_model(services.get_news_page(me.email, live=True)))


# ---- shared links (owner only) ---------------------------------------------------------------------------

def _owner(request: Request) -> views.Viewer:
    me = viewer(request)
    if not (config.OWNER_EMAIL and me.email == config.OWNER_EMAIL):
        raise HTTPException(404)
    return me


@app.get("/admin/links", response_class=HTMLResponse)
def admin_links(request: Request):
    _owner(request)
    return page(request, "links.html", links=services.get_share_links(), base=config.BASE_URL, mode=config.ACCESS_MODE,
                new=request.session.pop("new_link", None))


@app.post("/admin/links")
async def admin_links_create(request: Request):
    _owner(request)
    form = await request.form()
    request.session["new_link"] = services.create_share_link(str(form.get("label") or ""))
    return RedirectResponse("/admin/links", status_code=303)


@app.post("/admin/links/{token}/revoke")
def admin_links_revoke(request: Request, token: str):
    _owner(request)
    services.revoke_share_link(token)
    request.session["flash"] = "Link revoked. Visitors who used it lose access now, unless they signed in."
    return RedirectResponse("/admin/links", status_code=303)
