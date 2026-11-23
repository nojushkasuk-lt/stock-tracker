"""Publish one shared brief for the last completed week."""

from datetime import UTC, datetime

from tracker import config
from tracker.ai import llm, weekly_brief
from tracker.data import news
from tracker.data.edgar import EdgarClient
from tracker.data.filing_text import FilingFetcher
from tracker.db import session_scope


def main() -> None:
    if not (config.ANTHROPIC_API_KEY and config.BRAVE_SEARCH_API_KEY):
        print("Weekly brief needs the configured Anthropic and Brave API keys.")
        return
    fetcher = FilingFetcher(EdgarClient()) if config.EDGAR_USER_AGENT_EMAIL and config.EDGAR_USER_AGENT_NAME else None
    with session_scope() as session:
        try:
            row = weekly_brief.generate(session, news.BraveNews(), datetime.now(UTC).date(), fetcher=fetcher)
        except (llm.BudgetExceeded, news.SearchCapReached) as exc:
            print(f"Weekly brief skipped: {exc}")
            return
        except Exception as exc:
            # Commit usage that occurred before the failure, then fail the workflow.
            failure = exc
        else:
            print(f"Weekly brief available for the week ending {row.scope_key}." if row else "No sourced brief to publish.")
            return
    raise failure


if __name__ == "__main__":
    main()
