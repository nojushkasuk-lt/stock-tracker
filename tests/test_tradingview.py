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


def test_quotes_are_named_frames_so_browsers_restore_each_to_its_own_card():
    """Regression: with TradingView's async embed script, frames were created in random order and a reload or Back
    restored other companies' quotes into the cards (Anthropic showed AMD). Each quote is now our own iframe whose
    name is fixed per symbol, with the symbol in its own URL."""
    from html import unescape
    from urllib.parse import unquote

    from ui.tradingview import quote_html

    html = quote_html("NYSE:BRK.B")
    assert "<script" not in html
    frame = re.search(r'<iframe name="([^"]+)" src="([^"]+)"', html)
    assert frame.group(1) == "tv-quote-NYSE-BRK-B"
    src = unescape(frame.group(2))
    assert src.startswith("https://www.tradingview-widget.com/embed-widget/single-quote/?locale=en#")
    assert json.loads(unquote(src.split("#", 1)[1]))["symbol"] == "NYSE:BRK.B"
    assert "https://www.tradingview.com/symbols/NYSE-BRK.B/" in html and "by TradingView" in html
    names = [re.search(r'name="([^"]+)"', quote_html(s)).group(1) for s in ("NASDAQ:AMD", "NASDAQ:ANT", "NASDAQ:GOOGL")]
    assert len(set(names)) == 3
