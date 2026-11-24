"""Publish sourced closing coverage without persisting Tiingo quotes or returns."""

import argparse
import re
from datetime import date, datetime

from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from tracker import config
from tracker.ai import llm, notes, outputs, prompts
from tracker.ai.citations import Claim, Validator, render_sources
from tracker.data import news
from tracker.data.providers import tiingo
from tracker.db import session_scope
from tracker.models import AiOutput, Universe, UserWatchlist

MAX_SYMBOLS = 40  # Starter allows 50 requests per hour. SPY uses one additional request.
MAX_MOVER_NOTES = 8
NOTE_KIND = "closing_news"


class ClosingNote(BaseModel):
    claims: list[Claim] = Field(default_factory=list, max_length=3)


def _watchlist_symbols() -> dict[str, str]:
    with session_scope() as session:
        rows = session.execute(
            select(Universe.ticker, Universe.name)
            .where(Universe.cik != "", or_(
                Universe.is_demo & Universe.active,
                Universe.ticker.in_(select(UserWatchlist.ticker)),
            ))
            .order_by(Universe.is_demo.desc(), Universe.market_cap_rank.is_(None),
                      Universe.market_cap_rank, Universe.ticker)
            .limit(MAX_SYMBOLS)
        ).all()
    return dict(rows)


def _publish(session, brave, subject: str, ticker: str, day: date, direction: str | None) -> bool:
    prior = session.scalar(select(AiOutput.id).where(
        AiOutput.kind == NOTE_KIND, AiOutput.scope_key == ticker,
        AiOutput.content["date"].as_string() == day.isoformat(),
    ).limit(1))
    if prior is not None:
        return False
    query = news.coverage_query(subject, ticker, direction=direction) if direction else news.market_query()
    results = news.cached_search(session, brave, query, freshness=news.day_window(day), job=NOTE_KIND)
    links = news.coverage_links(results, news.load_outlets(), limit=8)
    if not links:
        return False
    sources = notes.sources_from_links(links)

    def validate(out: ClosingNote):
        validator = Validator(sources)
        # Publish qualitative coverage only. Drop diagnostics too, so rejected text is never stored.
        qualitative = [claim for claim in out.claims if not re.search(r"[\d%$€£]", claim.text)]
        claims = validator.claims("claims", qualitative)
        validator.checked.dropped.clear()
        # Keep source links even when the headlines do not support a clear explanation.
        validator.checked.cited_ids.update(source.id for source in sources)
        return ClosingNote(claims=claims), validator.checked

    try:
        row = outputs.generate(
            session, kind=NOTE_KIND, scope_key=ticker, job=NOTE_KIND, task="routine",
            system=prompts.load("rules") + "\nWrite up to three short cited claims about what reporting points to. "
                   "Use no numeric figures or price targets. If the sources do not explain the move, return no claims.",
            user=f"Closing coverage for {subject} on {day}.\n\n{render_sources(sources)}",
            output_model=ClosingNote, sources=sources, validate=validate,
            extra={"date": day.isoformat()}, max_tokens=750,
        )
    except llm.LLMError:
        # Search results are still useful when AI is unavailable or the budget is exhausted.
        row = outputs.save(
            session, kind=NOTE_KIND, scope_key=ticker, input_hash_=f"links:{day}",
            result=llm.LLMResult(ClosingNote(), "links-only", 0, 0, 0.0), sources=sources,
            validate=validate, extra={"date": day.isoformat()},
        )
    return row is not None


def main(day: date | None = None) -> None:
    if not (config.TIINGO_API_KEY and config.BRAVE_SEARCH_API_KEY):
        raise SystemExit("Closing news requires Tiingo and Brave API keys.")
    day = day or datetime.now(tiingo.NEW_YORK).date()
    symbols = _watchlist_symbols()
    changes = tiingo.closing_changes([*symbols, "SPY"], day)
    if "SPY" not in changes:
        print(f"No official SPY close for {day}. The session may be closed or the feed may still be updating.")
        return
    movers = sorted(
        ((ticker, changes[ticker]) for ticker in symbols
         if ticker in changes and abs(changes[ticker]) >= config.DEMO_MOVE_THRESHOLD_PCT),
        key=lambda pair: (-abs(pair[1]), pair[0]),
    )[:MAX_MOVER_NOTES]
    subjects = [("market", "U.S. stock market", None)]
    subjects.extend((ticker, symbols[ticker], "rose" if change > 0 else "fell") for ticker, change in movers)
    brave = news.BraveNews()
    published = 0
    for ticker, subject, direction in subjects:
        # Commit each result and its usage independently so a retry can skip completed notes.
        with session_scope() as session:
            try:
                published += _publish(session, brave, subject, ticker, day, direction)
            except news.SearchCapReached as exc:
                print(f"Closing news paused: {exc}")
                break
    print(f"{day}: published {published} closing news notes, checked {len(changes)} official closes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=date.fromisoformat, help="Trading session to backfill (YYYY-MM-DD)")
    main(parser.parse_args().date)
