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
