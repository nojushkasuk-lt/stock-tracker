"""Stock Tracker UI. Display only: all data comes from tracker.services; widgets come from ui."""

import streamlit as st

from tracker import services
from ui import financials as fin
from ui.text import md
from ui.chart import HEIGHT as CHART_FRAME_HEIGHT, chart_html
from ui.tradingview import (CALENDAR_HEIGHT, CHART_HEIGHT, FRAME_PAD, HEATMAP_HEIGHT, SYMBOL_INFO_HEIGHT,
                            calendar_html, chart_widget_html, heatmap_html, symbol_info_html)

st.set_page_config(page_title="Stock Tracker", page_icon="📈", layout="centered")
theme = "dark" if (st.context.theme.type or "light") == "dark" else "light"

st.markdown("## Stock Tracker")
st.caption("Demo: the 20 largest US companies. Read-only.")

stocks_tab, market_tab = st.tabs(["Stocks", "Market"])

with stocks_tab:
    stocks = services.get_demo_stocks()
    if not stocks:
        st.info("No stocks loaded yet. Run `python -m jobs.universe` to set up the database.")
    else:
        by_ticker = {s.ticker: s for s in stocks}
        ticker = st.selectbox("Stock", list(by_ticker), format_func=lambda t: f"{by_ticker[t].name} ({t})",
                              label_visibility="collapsed")
        stock = by_ticker[ticker]
        data = services.get_chart_data(stock.ticker)
        if data:
            st.iframe(chart_html(f"{stock.name} · {stock.ticker}", data.daily, data.intraday), height=CHART_FRAME_HEIGHT)
        else:  # no licensed chart data (e.g. in prod): TradingView widgets
            st.subheader(f"{stock.name} ({stock.ticker})")
            st.iframe(symbol_info_html(stock.tv_symbol, theme=theme), height=SYMBOL_INFO_HEIGHT + FRAME_PAD)
            st.iframe(chart_widget_html(stock.tv_symbol, theme=theme), height=CHART_HEIGHT + FRAME_PAD)
        st.caption(stock.industry)

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
            if not services.coverage_enabled():
                st.caption("Live coverage search is available to signed-in users.")
            else:
                outlets = services.get_outlets()
                chosen = st.multiselect("Outlets", [o.domain for o in outlets],
                                        format_func=lambda d: next(o.name for o in outlets if o.domain == d),
                                        placeholder="All outlets")
                if st.button("Find coverage", type="primary"):
                    cov = services.get_coverage(stock.ticker, set(chosen) or None)
                    if cov.message:
                        st.info(cov.message)
                    for link in cov.links:
                        when = f" · {link.published:%b %d, %H:%M} UTC" if link.published else ""
                        paywall = " · subscription" if link.paywall else ""
                        st.markdown(f"[{link.title}]({link.url})  \n:gray[{link.outlet}{when}{paywall}]")
                st.caption("Headlines and links only. Results are not stored.")

        with filings_tab:
            filings = services.get_recent_filings(stock.ticker)
            if not filings:
                st.caption("No filings checked yet. Run `python -m jobs.daily`.")
            for fl in filings:
                st.markdown(f"[{fl.label} ({fl.form})]({fl.url})  \n:gray[Filed {fl.filed}]")

with market_tab:
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

st.divider()
st.caption("For information only. Not investment advice.")
if services.coverage_enabled():
    st.caption("News search by Brave Search API.")
