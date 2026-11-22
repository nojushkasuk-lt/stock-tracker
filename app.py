"""Stock Tracker UI. Display only: all data comes from tracker.services."""

import streamlit as st

st.set_page_config(page_title="Stock Tracker", page_icon="📈", layout="wide")

st.title("Stock Tracker")
st.write("Follow the largest US stocks: charts, metrics and sourced AI explanations.")
st.info("Under construction. The demo of the 20 largest US companies is coming soon.")

st.divider()
st.caption("For information only. Not investment advice.")
