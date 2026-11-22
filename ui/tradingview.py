"""TradingView free embed widgets (AGENTS.md rule 13: prices and charts are shown only through these).

Pure HTML builders, no I/O. Each widget keeps its TradingView link (required by their terms).
"""

import json
import re
from html import escape

_EXCHANGE = {"nasdaq": "NASDAQ", "nyse": "NYSE", "cboe": "CBOE", "amex": "AMEX"}
_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
# Extra iframe height so the widget's "by TradingView" footer is not clipped.
FRAME_PAD = 30
CHART_HEIGHT = 520
SYMBOL_INFO_HEIGHT = 190
_SCRIPT = "https://s3.tradingview.com/external-embedding/embed-widget-{name}.js"


def tv_symbol(ticker: str, exchange: str | None) -> str:
    """'BRK-B' on NYSE -> 'NYSE:BRK.B' (TradingView writes share classes with a dot)."""
    ticker = ticker.upper()
    if not _TICKER_RE.match(ticker):
        raise ValueError(f"Invalid ticker {ticker!r}")
    sym = ticker.replace("-", ".")
    ex = _EXCHANGE.get((exchange or "").lower())
    return f"{ex}:{sym}" if ex else sym


def _symbol_url(symbol: str) -> str:
    return "https://www.tradingview.com/symbols/" + symbol.replace(":", "-") + "/"


def _widget(name: str, config: dict, link_text: str, symbol: str, height: int) -> str:
    # json.dumps of a dict we build ourselves; "<" is escaped so the payload can never close the script tag.
    payload = json.dumps(config).replace("<", "\\u003c")
    return f"""
<div class="tradingview-widget-container" style="height:{height}px;width:100%">
  <div class="tradingview-widget-container__widget" style="height:{height - 22}px;width:100%"></div>
  <div class="tradingview-widget-copyright" style="font:12px sans-serif;text-align:right">
    <a href="{escape(_symbol_url(symbol))}" rel="noopener nofollow" target="_blank">{escape(link_text)}</a>
    <span> by TradingView</span>
  </div>
  <script type="text/javascript" src="{_SCRIPT.format(name=name)}" async>{payload}</script>
</div>"""


def chart_widget_html(symbol: str, height: int = CHART_HEIGHT, theme: str = "light") -> str:
    """Advanced chart. Its own toolbar has the 1M / 1Y / 5Y / All ranges."""
    config = {
        "autosize": False, "width": "100%", "height": height - 22, "symbol": symbol, "interval": "D", "timezone": "Etc/UTC",
        "theme": theme, "style": "2", "locale": "en", "range": "12M",
        "allow_symbol_change": False, "calendar": False, "withdateranges": True, "hide_side_toolbar": True, "support_host": "https://www.tradingview.com",
    }
    return _widget("advanced-chart", config, f"{symbol.split(':')[-1]} chart", symbol, height)


def symbol_info_html(symbol: str, height: int = SYMBOL_INFO_HEIGHT, theme: str = "light") -> str:
    """Quote header: price, change, and key stats such as P/E and market cap."""
    config = {"symbol": symbol, "width": "100%", "locale": "en", "colorTheme": theme, "isTransparent": False}
    return _widget("symbol-info", config, f"{symbol.split(':')[-1]} quote", symbol, height)

