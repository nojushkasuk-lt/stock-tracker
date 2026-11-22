"""Stock Tracker UI. Display only: all data comes from tracker.services; widgets come from ui."""

import streamlit as st

from tracker import services
from ui import financials as fin
from ui.chart import HEIGHT as CHART_FRAME_HEIGHT, chart_html
from ui.tradingview import CHART_HEIGHT, FRAME_PAD, SYMBOL_INFO_HEIGHT, chart_widget_html, symbol_info_html

st.set_page_config(page_title="Stock Tracker", page_icon="📈", layout="centered")

st.markdown("## Stock Tracker")
st.caption("Demo: the 20 largest US companies. Read-only.")

stocks = services.get_demo_stocks()
if not stocks:
    st.info("No stocks loaded yet. Run `python -m jobs.universe` to set up the database.")
else:
    by_ticker = {s.ticker: s for s in stocks}
    ticker = st.selectbox(
        "Stock",
        list(by_ticker),
        format_func=lambda t: f"{by_ticker[t].name} ({t})",
        label_visibility="collapsed",
    )
    stock = by_ticker[ticker]
    data = services.get_chart_data(stock.ticker)
    if data:
        st.iframe(chart_html(f"{stock.name} · {stock.ticker}", data.daily, data.intraday), height=CHART_FRAME_HEIGHT)
    else:  # no licensed chart data (e.g. in prod): TradingView widgets
        st.subheader(f"{stock.name} ({stock.ticker})")
        st.iframe(symbol_info_html(stock.tv_symbol), height=SYMBOL_INFO_HEIGHT + FRAME_PAD)
        st.iframe(chart_widget_html(stock.tv_symbol), height=CHART_HEIGHT + FRAME_PAD)
    st.caption(stock.industry)

    f = services.get_financials(stock.ticker)
    if f:
        st.markdown("#### Financials")
        st.caption(fin.as_of_text(f.metrics.as_of))
        for row in (fin.cards(f.metrics)[:3], fin.cards(f.metrics)[3:]):
            for col, c in zip(st.columns(3), row):
                col.metric(c["label"], c["value"], c.get("delta"), help=c["help"])
        fig = fin.revenue_margin_figure(f.history)
        if fig:
            st.markdown("#### Revenue and margin by year")
            st.plotly_chart(fig, config={"displayModeBar": False})

st.divider()
st.caption("For information only. Not investment advice.")
