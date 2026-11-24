"""TradingView free embed widgets (AGENTS.md rule 13: prices and charts are shown only through these).

Pure HTML builders, no I/O. Each widget keeps its TradingView link (required by their terms).
"""

import json
import re
from html import escape
from urllib.parse import urlencode

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


def symbol_url(symbol: str) -> str:
    return "https://www.tradingview.com/symbols/" + symbol.replace(":", "-") + "/"


def chart_url(symbol: str) -> str:
    return "https://www.tradingview.com/chart/?" + urlencode({"symbol": symbol})


def _widget(name: str, config: dict, link_text: str, symbol: str | None, height: int, link: str | None = None) -> str:
    # json.dumps of a dict we build ourselves; "<" is escaped so the payload can never close the script tag.
    payload = json.dumps(config).replace("<", "\\u003c")
    return f"""
<div class="tradingview-widget-container" style="height:{height}px;width:100%">
  <div class="tradingview-widget-container__widget" style="height:{height - 22}px;width:100%"></div>
  <div class="tradingview-widget-copyright" style="font:12px sans-serif;text-align:right">
    <a href="{escape(link or symbol_url(symbol))}" rel="noopener nofollow" target="_blank">{escape(link_text)}</a>
    <span> by TradingView</span>
  </div>
  <script type="text/javascript" src="{_SCRIPT.format(name=name)}" async>{payload}</script>
</div>"""


MIDNIGHT_BG = "#121E33"    # the site's card colour, so the chart sits inside the card
MIDNIGHT_GRID = "#1C2A44"


def chart_widget_html(symbol: str, height: int = CHART_HEIGHT, theme: str = "light",
                      background: str | None = None, grid: str | None = None) -> str:
    """Advanced chart. Its own toolbar has the 1M / 1Y / 5Y / All ranges."""
    config = {
        "autosize": False, "width": "100%", "height": height - 22, "symbol": symbol, "interval": "D", "timezone": "Etc/UTC",
        "theme": theme, "style": "2", "locale": "en", "range": "12M",
        "allow_symbol_change": False, "calendar": False, "withdateranges": True, "hide_side_toolbar": True, "support_host": "https://www.tradingview.com",
    }
    if background:
        config["backgroundColor"] = background
    if grid:
        config["gridColor"] = grid
    return _widget("advanced-chart", config, f"{symbol.split(':')[-1]} chart", symbol, height)


def symbol_info_html(symbol: str, height: int = SYMBOL_INFO_HEIGHT, theme: str = "light") -> str:
    """Quote header: price, change, and key stats such as P/E and market cap."""
    config = {"symbol": symbol, "width": "100%", "locale": "en", "colorTheme": theme, "isTransparent": False}
    return _widget("symbol-info", config, f"{symbol.split(':')[-1]} quote", symbol, height)


QUOTE_HEIGHT = 96


def quote_html(symbol: str, theme: str = "dark") -> str:
    """Compact TradingView quote with price and day change."""
    config = {"symbol": symbol, "width": "100%", "isTransparent": True, "colorTheme": theme, "locale": "en"}
    return _widget("single-quote", config, f"{symbol.split(':')[-1]} quote", symbol, QUOTE_HEIGHT)


HEATMAP_HEIGHT = 520
CALENDAR_HEIGHT = 520


def heatmap_html(theme: str = "light", height: int = HEATMAP_HEIGHT) -> str:
    """S&P 500 heatmap: tiles sized by market cap, coloured by today's change, grouped by sector."""
    config = {
        "exchanges": [], "dataSource": "SPX500", "grouping": "sector", "blockSize": "market_cap_basic",
        "blockColor": "change", "locale": "en", "colorTheme": theme, "hasTopBar": False,
        "isDataSetEnabled": False, "isZoomEnabled": True, "hasSymbolTooltip": True, "isMonoSize": False,
        "width": "100%", "height": height - 22,
    }
    return _widget("stock-heatmap", config, "S&P 500 heatmap", None, height,
                   link="https://www.tradingview.com/heatmap/stock/")


def calendar_html(theme: str = "light", height: int = CALENDAR_HEIGHT) -> str:
    """US economic calendar (CPI, jobs, Fed decisions), medium and high importance."""
    config = {
        "colorTheme": theme, "isTransparent": True, "width": "100%", "height": height - 22, "locale": "en",
        "importanceFilter": "0,1", "countryFilter": "us",
    }
    return _widget("events", config, "Economic calendar", None, height,
                   link="https://www.tradingview.com/economic-calendar/")
