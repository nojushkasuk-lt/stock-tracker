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

# SEC EDGAR (rule 9: User-Agent with a name and contact email; stay under 10 requests per second)
EDGAR_USER_AGENT_NAME = os.environ.get("EDGAR_USER_AGENT_NAME", "")
EDGAR_USER_AGENT_EMAIL = os.environ.get("EDGAR_USER_AGENT_EMAIL", "")

# Custom chart data. Local dev defaults to yfinance; prod defaults to "none" (TradingView widgets) until a
# licensed provider is recorded in docs/data-licensing.md (AGENTS.md rule 13).
CHART_PROVIDER = os.environ.get("CHART_PROVIDER") or ("none" if APP_ENV == "prod" else "yfinance_dev")
CHART_CACHE_SECONDS = _int("CHART_CACHE_SECONDS", 1800)  # in-memory only, under 1 hour

# Brave News Search (live queries only; results kept in memory, never stored: AGENTS.md rule 13)
BRAVE_SEARCH_API_KEY = os.environ.get("BRAVE_SEARCH_API_KEY", "")
NEWS_CACHE_SECONDS = _int("NEWS_CACHE_SECONDS", 1800)  # must stay under 1 hour
COVERAGE_RESULTS = _int("COVERAGE_RESULTS", 10)
