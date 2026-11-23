"""Stock Tracker UI. Display only: all data comes from tracker.services; widgets come from ui."""

import streamlit as st

from tracker import services
from ui import financials as fin
from ui.chart import HEIGHT as CHART_FRAME_HEIGHT, chart_html
from ui.notes import move_note
from ui.text import md
from ui.tradingview import (CALENDAR_HEIGHT, CHART_HEIGHT, FRAME_PAD, HEATMAP_HEIGHT, SYMBOL_INFO_HEIGHT,
                            calendar_html, chart_widget_html, heatmap_html, symbol_info_html)

st.set_page_config(page_title="Stock Tracker", page_icon="📈", layout="centered")
theme = "dark" if (st.context.theme.type or "light") == "dark" else "light"


# ---- who is this? --------------------------------------------------------------------------------

def google_auth_configured() -> bool:
    try:
        return "auth" in st.secrets
    except Exception:  # no secrets file
        return False


def current_email() -> str | None:
    if google_auth_configured():
        return st.user.email if st.user.is_logged_in else None
    return st.session_state.get("dev_email")


email = current_email()
if email and st.session_state.get("signed_in_as") != email:
    services.sign_in(email)
    st.session_state["signed_in_as"] = email

top_l, top_r = st.columns([3, 1], vertical_alignment="center")
top_l.markdown("## Stock Tracker")
with top_r:
    if email:
        if st.button("Sign out", use_container_width=True):
            st.session_state.pop("dev_email", None)
            st.session_state.pop("signed_in_as", None)
            st.logout() if google_auth_configured() else st.rerun()
    elif google_auth_configured():
        if st.button("Sign in with Google", type="primary", use_container_width=True):
            st.login()
if not email and not google_auth_configured() and services.dev_sign_in_allowed():
    with st.expander("Local dev sign-in (no Google OAuth configured)"):
        dev = st.text_input("Email", placeholder="you@example.com")
        if st.button("Sign in locally") and "@" in dev:
            st.session_state["dev_email"] = dev.strip().lower()
            st.rerun()

if email:
    st.caption(f"Signed in as {email}.")
else:
    st.caption("Demo: the 20 largest US companies. Read-only. Sign in to follow up to 15 of the 100 largest.")

tab_names = ["Stocks", "Market"] + (["Settings"] if email else [])
tabs = dict(zip(tab_names, st.tabs(tab_names)))


# ---- stocks --------------------------------------------------------------------------------------

def stock_page(stock) -> None:
    data = services.get_chart_data(stock.ticker)
    if data:
        st.iframe(chart_html(f"{stock.name} · {stock.ticker}", data.daily, data.intraday), height=CHART_FRAME_HEIGHT)
    else:  # no licensed chart data (e.g. in prod): TradingView widgets
        st.subheader(f"{stock.name} ({stock.ticker})")
        st.iframe(symbol_info_html(stock.tv_symbol, theme=theme), height=SYMBOL_INFO_HEIGHT + FRAME_PAD)
        st.iframe(chart_widget_html(stock.tv_symbol, theme=theme), height=CHART_HEIGHT + FRAME_PAD)
    st.caption(stock.industry)

    note = services.get_move_note(stock.ticker, email)
    if note:
        move_note(note, "Latest move")
    if email:
        left = services.refreshes_left(email)
        c1, c2 = st.columns([1, 3], vertical_alignment="center")
        if c1.button("Refresh now", disabled=left == 0, help="Search the news again and rewrite the note"):
            with st.spinner("Searching and writing a fresh note..."):
                st.session_state["refresh_msg"] = services.request_refresh(email, stock.ticker)
            st.rerun()
        c2.caption(st.session_state.pop("refresh_msg", None) or f"{left} refreshes left today.")

    profile_tab, overview, news_tab, filings_tab = st.tabs(["Profile", "Financials", "Coverage", "Filings"])
    with profile_tab:
        prof = services.get_profile(stock.ticker)
        if prof is None:
            st.caption("No AI profile yet. It is written when the company files its next report.")
        else:
            for title, points in prof.sections:
                st.markdown(f"##### {title}")
                for p in points:
                    refs = " · ".join(f"[{md(l.label)}]({l.url})" if l.url else md(l.label) for l in p.sources)
                    st.markdown(f"- {md(p.text)}  \n  :gray[{refs}]")
            if prof.what_changed:
                st.markdown(f"**What changed:** {md(prof.what_changed)}")
            st.caption(f"Written by AI from the company's SEC filings on {prof.updated}. Every point links to "
                       "its source. For information only. Not investment advice.")
    with overview:
        f = services.get_financials(stock.ticker)
        if f:
            st.caption(fin.as_of_text(f.metrics.as_of))
            cards = fin.cards(f.metrics)
            for row in (cards[:3], cards[3:]):
                for col, c in zip(st.columns(3), row):
                    col.metric(c["label"], c["value"], c.get("delta"), help=c["help"])
            fig = fin.revenue_margin_figure(f.history)
            if fig:
                st.markdown("##### Revenue and margin by year")
                st.plotly_chart(fig, config={"displayModeBar": False})
    with news_tab:
        if not services.coverage_enabled(email):
            st.caption("Live coverage search is available to signed-in users.")
        else:
            domains = services.get_outlet_choice(email) or None
            if st.button("Find coverage", type="primary"):
                cov = services.get_coverage(stock.ticker, domains, email)
                if cov.message:
                    st.info(cov.message)
                for link in cov.links:
                    when = f" · {link.published:%b %d, %H:%M} UTC" if link.published else ""
                    paywall = " · subscription" if link.paywall else ""
                    st.markdown(f"[{md(link.title)}]({link.url})  \n:gray[{link.outlet}{when}{paywall}]")
            st.caption(f"From your chosen outlets (Settings). {services.coverage_searches_left(email)} searches left "
                       "today. Headlines and links only; results are not stored.")
    with filings_tab:
        filings = services.get_recent_filings(stock.ticker)
        if not filings:
            st.caption("No filings checked yet. Run `python -m jobs.daily`.")
        for fl in filings:
            st.markdown(f"[{fl.label} ({fl.form})]({fl.url})  \n:gray[Filed {fl.filed}]")


with tabs["Stocks"]:
    stocks = services.get_watchlist(email) if email else services.get_demo_stocks()
    if email and not stocks:
        st.info("You don't follow any stocks yet. Pick up to 15 in the Settings tab.")
    elif not stocks:
        st.info("No stocks loaded yet. Run `python -m jobs.universe` to set up the database.")
    else:
        by_ticker = {s.ticker: s for s in stocks}
        ticker = st.selectbox("Stock", list(by_ticker), format_func=lambda t: f"{by_ticker[t].name} ({t})",
                              label_visibility="collapsed")
        stock_page(by_ticker[ticker])


# ---- market --------------------------------------------------------------------------------------

with tabs["Market"]:
    ms = services.get_market_status(email)
    if ms and ms.level != "none":
        word = "fell" if ms.index_return_pct < 0 else "rose"
        alert = st.error if ms.level == "major" else st.warning
        alert(f"Market alert: the S&P 500 {word} {abs(ms.index_return_pct):.1f}% on {ms.date}.")
        if ms.note:
            move_note(ms.note, "S&P 500")
    elif ms:
        st.caption(f"S&P 500 {ms.index_return_pct:+.1f}% on {ms.date}. No market alert (alerts start at a 2% move).")
    st.markdown("##### S&P 500 today")
    st.iframe(heatmap_html(theme), height=HEATMAP_HEIGHT + FRAME_PAD)
    st.markdown("##### Economic calendar")
    st.iframe(calendar_html(theme), height=CALENDAR_HEIGHT + FRAME_PAD)
    st.markdown("##### Official sources")
    st.markdown(
        "- [Federal Reserve: FOMC meeting calendar](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)\n"
        "- [US Treasury: daily yield curve rates](https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve)\n"
        "- [Bureau of Labor Statistics: consumer prices (CPI)](https://www.bls.gov/cpi/)\n"
        "- [Bureau of Labor Statistics: jobs report](https://www.bls.gov/news.release/empsit.toc.htm)"
    )


# ---- settings (signed in) ------------------------------------------------------------------------

if email:
    with tabs["Settings"]:
        st.markdown("##### Your stocks")
        followable = services.get_followable_stocks(email)
        names = {s.ticker: s.name for s in followable}
        mine = [s.ticker for s in services.get_watchlist(email)]
        picked = st.multiselect(f"Pick up to {services.watchlist_max()} of the 100 largest US companies",
                                list(names), default=mine, max_selections=services.watchlist_max(),
                                format_func=lambda t: f"{names[t]} ({t})")
        st.markdown("##### News outlets")
        outlets = services.get_outlets()
        chosen = st.multiselect("Coverage links come only from these outlets (none chosen = all)",
                                [o.domain for o in outlets], default=sorted(services.get_outlet_choice(email)),
                                format_func=lambda d: next(o.name for o in outlets if o.domain == d))
        if st.button("Save", type="primary"):
            err = services.save_watchlist(email, picked)
            if err:
                st.error(err)
            else:
                services.save_outlet_choice(email, chosen)
                st.success("Saved.")


st.divider()
st.caption("For information only. Not investment advice.")
st.caption("News search by Brave Search API.")
