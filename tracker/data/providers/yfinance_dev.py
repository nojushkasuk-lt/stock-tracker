"""yfinance provider. LOCAL DEVELOPMENT ONLY: Yahoo's terms are personal-use. Refuses to run when APP_ENV=prod."""

from datetime import date, timedelta

from tracker import config


class ProviderNotAllowed(RuntimeError):
    pass


class YFinanceDev:
    def __init__(self) -> None:
        if config.APP_ENV == "prod":
            raise ProviderNotAllowed("yfinance_dev is for local development only and must not run when APP_ENV=prod")

    def daily_returns(self, tickers: list[str], start: date, end: date | None = None):
        import yfinance as yf

        end = end or date.today() + timedelta(days=1)
        df = yf.download(
            tickers, start=start.isoformat(), end=end.isoformat(),
            auto_adjust=True, progress=False, group_by="column", threads=True,
        )
        closes = df["Close"]
        if len(tickers) == 1 and not hasattr(closes, "columns"):
            closes = closes.to_frame(tickers[0])
        # Prices stay inside this function; only percent changes leave it.
        pct = closes.pct_change(fill_method=None) * 100
        out = {}
        for t in closes.columns:
            s = pct[t].dropna()
            if len(s):
                out[t] = [(i.date(), float(v)) for i, v in s.items()]
        return out

    def market_caps(self, tickers: list[str]) -> dict[str, float]:
        import yfinance as yf
        from concurrent.futures import ThreadPoolExecutor

        def one(t: str):
            try:
                v = yf.Ticker(t).fast_info["market_cap"]
                return t, float(v) if v else None
            except Exception:
                return t, None

        with ThreadPoolExecutor(max_workers=8) as ex:
            return {t: v for t, v in ex.map(one, tickers) if v}

    def daily_closes(self, ticker: str) -> list[tuple[date, float]]:
        """Full daily close history (split/dividend adjusted). Dev only; never stored."""
        import yfinance as yf

        hist = yf.Ticker(ticker).history(period="max", auto_adjust=True)
        closes = hist["Close"].dropna()
        return [(i.date(), float(v)) for i, v in closes.items()]

    def intraday(self, ticker: str) -> dict[str, list[tuple[int, float]]]:
        """{"1W": 15-minute closes of the last 5 sessions, "1D": 5-minute closes of the last session}.
        Times are UTC epoch seconds. Dev only; never stored."""
        import yfinance as yf

        out: dict[str, list[tuple[int, float]]] = {}
        for key, interval in (("1W", "15m"), ("1D", "5m")):
            closes = yf.Ticker(ticker).history(period="5d", interval=interval, auto_adjust=True)["Close"].dropna()
            if closes.empty:
                continue
            if key == "1D":
                closes = closes[[i.date() == closes.index[-1].date() for i in closes.index]]
            out[key] = [(int(i.timestamp()), float(v)) for i, v in closes.items()]
        return out
