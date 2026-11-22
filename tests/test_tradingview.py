import json
import re

import pytest

from ui.tradingview import chart_widget_html, symbol_info_html, tv_symbol


def test_symbol_formats():
    assert tv_symbol("AAPL", "Nasdaq") == "NASDAQ:AAPL"
    assert tv_symbol("BRK-B", "NYSE") == "NYSE:BRK.B"
    assert tv_symbol("aapl", None) == "AAPL"  # unknown exchange: bare ticker


@pytest.mark.parametrize("bad", ["", "AA PL", "</script>", "A;B", "TOOLONGTICKERX1"])
def test_rejects_bad_tickers(bad):
    with pytest.raises(ValueError):
        tv_symbol(bad, "NYSE")


@pytest.mark.parametrize("build", [chart_widget_html, symbol_info_html])
def test_widgets_keep_the_tradingview_link_and_valid_json(build):
    html = build("NYSE:BRK.B")
    assert "https://www.tradingview.com/symbols/NYSE-BRK.B/" in html
    assert "by TradingView" in html
    payload = re.search(r"<script[^>]*>(.*)</script>", html, re.S).group(1)
    assert json.loads(payload)["symbol"] == "NYSE:BRK.B"



@pytest.mark.parametrize("build,link", [
    ("heatmap_html", "https://www.tradingview.com/heatmap/stock/"),
    ("calendar_html", "https://www.tradingview.com/economic-calendar/"),
])
def test_market_widgets_keep_their_tradingview_link(build, link):
    import ui.tradingview as tv

    html = getattr(tv, build)("dark")
    assert link in html and "by TradingView" in html
    payload = json.loads(re.search(r"<script[^>]*>(.*)</script>", html, re.S).group(1))
    assert payload["colorTheme"] == "dark"
