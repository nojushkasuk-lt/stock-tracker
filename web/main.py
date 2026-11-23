"""Stock Tracker website (FastAPI + server-rendered Jinja pages).

Display only, like the Streamlit app it replaces (AGENTS.md rule 1): every piece of data comes from
tracker.services, widgets come from ui.tradingview. Jinja autoescapes all text, including model output.

Run locally:  uvicorn web.main:app --reload   (then open http://localhost:8000)
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from tracker import config, services
from ui import tradingview as tv
from web import auth, views

HERE = Path(__file__).resolve().parent

app = FastAPI(title="Stock Tracker", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=config.SESSION_SECRET or "dev-only-not-secret",
                   same_site="lax", https_only=config.APP_ENV == "prod", max_age=60 * 60 * 24 * 30)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
views.register_filters(templates.env)
templates.env.globals.update(credit=config.OWNER_CREDIT)
auth.register(app)


def viewer(request: Request) -> views.Viewer:
    s = request.session
    return views.Viewer(email=s.get("email"), name=s.get("name"), demo=bool(s.get("demo")) and not s.get("email"))


def page(request: Request, name: str, **ctx) -> HTMLResponse:
    ctx.setdefault("flash", request.session.pop("flash", None))
    return templates.TemplateResponse(request, name, {"me": viewer(request), **ctx})


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
    if me.email or me.demo:
        return RedirectResponse("/portfolio", status_code=303)
    return page(request, "start.html", google=auth.configured(), dev_login=auth.dev_login_allowed())


@app.get("/demo")
def demo(request: Request):
    request.session.clear()
    request.session["demo"] = True
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
    return page(request, "portfolio.html", cards=cards, market=services.get_market_status(me.email),
                summary=views.day_summary(cards), note=note, note_stock=note_stock,
                max_stocks=services.watchlist_max(), nav="portfolio")


# ---- stock page -----------------------------------------------------------------------------------

def _stock_or_404(me: views.Viewer, ticker: str):
    stock = services.get_stock(ticker)
    if stock is None:
        raise HTTPException(404, "Unknown stock")
    if me.demo and stock.ticker not in {s.ticker for s in services.get_demo_stocks()}:
        raise HTTPException(404, "The demo covers the 20 largest US companies. Sign in to see this stock.")
    return stock


def _stock_page(request: Request, ticker: str, coverage=None):
    me = require_viewer(request)
    stock = _stock_or_404(me, ticker)
    following = bool(me.email) and stock.ticker in {s.ticker for s in services.get_watchlist(me.email)}
    perf = services.get_performance(stock.ticker)
    model = views.stock_model(
        stock=stock, perf=perf, profile=services.get_profile(stock.ticker),
        financials=services.get_financials(stock.ticker), note=services.get_move_note(stock.ticker, me.email),
        filings=services.get_recent_filings(stock.ticker), coverage=coverage)
    theme = "dark"
    return page(
        request, "stock.html", s=stock, m=model, following=following, nav="stocks",
        local_chart=config.APP_ENV == "local" and perf is not None,
        chart_widget=tv.chart_widget_html(stock.tv_symbol, theme=theme),
        quote_widget=tv.symbol_info_html(stock.tv_symbol, theme=theme),
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
                heatmap=tv.heatmap_html("dark"), calendar=tv.calendar_html("dark"))


# ---- settings (signed in only) ---------------------------------------------------------------------

@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request, error: str | None = None):
    me = require_viewer(request)
    if not me.email:
        return RedirectResponse("/", status_code=303)
    mine = [s.ticker for s in services.get_watchlist(me.email)]
    return page(request, "settings.html", nav="settings", stocks=services.get_followable_stocks(me.email),
                mine=set(mine), outlets=services.get_outlets(), my_outlets=services.get_outlet_choice(me.email),
                max_stocks=services.watchlist_max(), error=error)


@app.post("/settings")
async def settings_save(request: Request):
    me = require_viewer(request)
    if not me.email:
        return RedirectResponse("/", status_code=303)
    form = await request.form()
    err = services.save_watchlist(me.email, list(form.getlist("ticker")))
    if err:
        return settings(request, error=err)
    services.save_outlet_choice(me.email, list(form.getlist("outlet")))
    request.session["flash"] = "Saved."
    return RedirectResponse("/portfolio", status_code=303)
