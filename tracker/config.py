"""Settings from the environment (and a local .env file). Streamlit secrets are exported to env by app.py later."""

import os
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader: KEY=VALUE lines; real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


_load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name) or default)


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name) or default)


APP_ENV = os.environ.get("APP_ENV") or "local"
DATABASE_URL = os.environ.get("DATABASE_URL") or "sqlite:///stock_tracker.db"

MONTHLY_BUDGET_USD = _float("MONTHLY_BUDGET_USD", 8.00)
MONTHLY_SEARCH_CAP = _int("MONTHLY_SEARCH_CAP", 900)

PRICE_PROVIDER = os.environ.get("PRICE_PROVIDER") or "yfinance_dev"

# Universe refresh
UNIVERSE_SIZE = _int("UNIVERSE_SIZE", 100)
DEMO_SIZE = _int("DEMO_SIZE", 20)
# A current member only drops out when it falls below this rank (stops flip-flopping at the boundary).
UNIVERSE_EXIT_RANK = _int("UNIVERSE_EXIT_RANK", 110)
# Europe and Asia: the largest SEC-registered foreign filers (20-F) from config/international.csv, per region.
INTL_REGIONS = ("Europe", "Asia")
INTL_SIZE = _int("INTL_SIZE", 25)  # seats per region
INTL_EXIT_RANK = _int("INTL_EXIT_RANK", 30)

# SEC EDGAR (rule 9: User-Agent with a name and contact email; stay under 10 requests per second)
EDGAR_USER_AGENT_NAME = os.environ.get("EDGAR_USER_AGENT_NAME", "")
EDGAR_USER_AGENT_EMAIL = os.environ.get("EDGAR_USER_AGENT_EMAIL", "")

# Custom chart data. Local dev defaults to yfinance; prod defaults to "none" (TradingView widgets) until a
# licensed provider is recorded in docs/data-licensing.md (AGENTS.md rule 13).
# Who sees figures made from the price provider (daily % changes, returns, risk, move notes, alerts):
# "owner" until docs/data-licensing.md records permission to show them to others (rule 13), then "all".
PRICE_DATA_DISPLAY = (os.environ.get("PRICE_DATA_DISPLAY") or ("owner" if APP_ENV == "prod" else "all")).lower()
CHART_PROVIDER = os.environ.get("CHART_PROVIDER") or ("none" if APP_ENV == "prod" else "yfinance_dev")
CHART_CACHE_SECONDS = _int("CHART_CACHE_SECONDS", 1800)  # in-memory only, under 1 hour

# Brave News Search (live queries only; results kept in memory, never stored: AGENTS.md rule 13)
BRAVE_SEARCH_API_KEY = os.environ.get("BRAVE_SEARCH_API_KEY", "")
NEWS_CACHE_SECONDS = _int("NEWS_CACHE_SECONDS", 1800)  # must stay under 1 hour
COVERAGE_RESULTS = _int("COVERAGE_RESULTS", 10)

# Anthropic (every model call goes through tracker/ai/llm.py: AGENTS.md rule 2)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL_ROUTINE = os.environ.get("MODEL_ROUTINE") or "claude-haiku-5-5"  # notes, link ranking, summaries
MODEL_PROFILE = os.environ.get("MODEL_PROFILE") or "claude-sonnet-5-5"  # filing-based profile updates
EFFORT_ROUTINE = os.environ.get("EFFORT_ROUTINE") or "medium"
EFFORT_PROFILE = os.environ.get("EFFORT_PROFILE") or "medium"
# Haiku's price rises fivefold above 100k prompt tokens (rule 5); we refuse prompts above this.
MAX_PROMPT_TOKENS = _int("MAX_PROMPT_TOKENS", 100_000)

# Moves and the attribution ladder (AGENTS.md rule 14)
MARKET_ALERT_PCT = _float("MARKET_ALERT_PCT", 2.0)
MARKET_MAJOR_PCT = _float("MARKET_MAJOR_PCT", 3.0)
MOVE_THRESHOLD_PCT = _float("MOVE_THRESHOLD_PCT", 5.0)
DEMO_MOVE_THRESHOLD_PCT = _float("DEMO_MOVE_THRESHOLD_PCT", 3.0)
RESIDUAL_PCT = _float("RESIDUAL_PCT", 3.0)
INDUSTRY_MIN_PEERS = _int("INDUSTRY_MIN_PEERS", 3)
INDUSTRY_MOVE_PCT = _float("INDUSTRY_MOVE_PCT", 3.0)
RECHECK_AFTER_HOURS = _float("RECHECK_AFTER_HOURS", 8.0)  # rule 14: recheck unexplained moves after 6-12 hours
MARKET_NOTE_MIN_INTERVAL_HOURS = _float("MARKET_NOTE_MIN_INTERVAL_HOURS", 3.0)

# Users and caps (AGENTS.md rule 6)
WATCHLIST_MAX = _int("WATCHLIST_MAX", 15)
REFRESH_PER_USER_PER_DAY = _int("REFRESH_PER_USER_PER_DAY", 3)
REFRESH_PER_MONTH = _int("REFRESH_PER_MONTH", 300)
REFRESH_SHARE_HOURS = _float("REFRESH_SHARE_HOURS", 6.0)  # a refresh of a ticker is shared with everyone
COVERAGE_SEARCHES_PER_USER_PER_DAY = _int("COVERAGE_SEARCHES_PER_USER_PER_DAY", 10)

# Web app (web/): Google sign-in and signed session cookies
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID") or ""
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET") or ""
SESSION_SECRET = os.environ.get("SESSION_SECRET") or ""
BASE_URL = (os.environ.get("BASE_URL") or "http://localhost:8000").rstrip("/")
OWNER_CREDIT = "Designed and built by Nojus Šukaitis"

# Private access (see web/access.py). ACCESS_MODE=open: anyone with the URL (local default);
# ACCESS_MODE=link: only visitors who opened a shared link (or signed in before) get past the gate.
ACCESS_MODE = (os.environ.get("ACCESS_MODE") or ("link" if APP_ENV == "prod" else "open")).lower()
OWNER_EMAIL = (os.environ.get("OWNER_EMAIL") or "").strip().lower()  # can create and revoke shared links
# Email alerts: off until a sending service is chosen and configured.
EMAIL_PROVIDER = (os.environ.get("EMAIL_PROVIDER") or "none").lower()
SMTP_HOST = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
SMTP_PORT = _int("SMTP_PORT", 465)
SMTP_USER = (os.environ.get("SMTP_USER") or "").strip()
SMTP_APP_PASSWORD = (os.environ.get("SMTP_APP_PASSWORD") or "").replace(" ", "")
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME") or "Stock Tracker"
EMAIL_MAX_ITEMS = _int("EMAIL_MAX_ITEMS", 10)   # alerts per email; the rest are on the Alerts page


def email_ready() -> bool:
    return EMAIL_PROVIDER == "gmail" and bool(SMTP_USER and SMTP_APP_PASSWORD)
