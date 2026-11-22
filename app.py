"""Stock Tracker UI. Display only: all data comes from tracker.services; widgets come from ui."""

import streamlit as st

from tracker import services
from ui.tradingview import CHART_HEIGHT, FRAME_PAD, SYMBOL_INFO_HEIGHT, chart_widget_html, symbol_info_html

st.set_page_config(page_title="Stock Tracker", page_icon="📈", layout="wide")

st.title("Stock Tracker")
st.caption("Demo: the 20 largest US companies. Read-only.")

stocks = services.get_demo_stocks()
if not stocks:
    st.info("No stocks loaded yet. Run `python -m jobs.universe` to set up the database.")
else:
    by_ticker = {s.ticker: s for s in stocks}
    with st.sidebar:
        st.header("Demo stocks")
        ticker = st.selectbox(
            "Stock",
            list(by_ticker),
            format_func=lambda t: f"{by_ticker[t].rank}. {t} — {by_ticker[t].name}",
        )
    stock = by_ticker[ticker]
    st.subheader(f"{stock.name} ({stock.ticker})")
    st.caption(stock.industry)
    st.iframe(symbol_info_html(stock.tv_symbol), height=SYMBOL_INFO_HEIGHT + FRAME_PAD)
    st.iframe(chart_widget_html(stock.tv_symbol), height=CHART_HEIGHT + FRAME_PAD)

st.divider()
st.caption("For information only. Not investment advice.")
