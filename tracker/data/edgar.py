"""SEC EDGAR client. Rule 9: User-Agent with a name and contact email from config; under 10 requests/second."""

import time

import httpx

from tracker import config

TICKERS_EXCHANGE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
MIN_INTERVAL = 0.12  # seconds between requests (about 8 per second)


class EdgarConfigError(RuntimeError):
    pass


class EdgarClient:
    def __init__(self, client: httpx.Client | None = None, name: str | None = None, email: str | None = None):
        name = name if name is not None else config.EDGAR_USER_AGENT_NAME
        email = email if email is not None else config.EDGAR_USER_AGENT_EMAIL
        if not name or "@" not in email:
            raise EdgarConfigError("Set EDGAR_USER_AGENT_NAME and EDGAR_USER_AGENT_EMAIL (SEC requires contact details)")
        self._client = client or httpx.Client(timeout=60)
        self._headers = {"User-Agent": f"{name} {email}"}
        self._last = 0.0

    def get_json(self, url: str) -> dict:
        wait = self._last + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        r = self._client.get(url, headers=self._headers)
        r.raise_for_status()
        return r.json()

    def tickers_exchange(self) -> list[dict]:
        """All SEC-registered tickers with exchange: [{cik, name, ticker, exchange}]."""
        d = self.get_json(TICKERS_EXCHANGE_URL)
        return [dict(zip(d["fields"], row)) for row in d["data"]]

    def companyfacts(self, cik: int) -> dict:
        return self.get_json(COMPANYFACTS_URL.format(cik=int(cik)))

    def submissions(self, cik: int) -> dict:
        return self.get_json(SUBMISSIONS_URL.format(cik=int(cik)))


DOMESTIC_FORMS = {"10-K", "10-Q"}
IPO_FORMS = {"S-1", "S-1/A", "424B4", "10-12B"}
FOREIGN_FORMS = {"20-F", "40-F", "6-K", "F-1", "F-1/A"}


def is_domestic_filer(submissions: dict) -> bool:
    """US domestic registrant: files 10-K/10-Q, or a brand-new IPO that shows an IPO form and no foreign forms."""
    forms = set(submissions.get("filings", {}).get("recent", {}).get("form", []))
    if forms & DOMESTIC_FORMS:
        return True
    return bool(forms & IPO_FORMS) and not (forms & FOREIGN_FORMS)
