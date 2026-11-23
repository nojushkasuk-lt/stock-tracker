"""A shared market and technology briefing for the last completed week."""

from datetime import date, datetime, time, timedelta

import httpx
from sqlalchemy import select

from pydantic import BaseModel, Field

from tracker.ai import outputs, prompts
from tracker.ai.citations import Checked, Claim, Source, Validator, render_sources
from tracker.ai.notes import sources_from_links
from tracker.data import news
from tracker.data.filing_text import cap
from tracker.models import Filing, Universe

KIND = "weekly_brief"
TOPICS = {
    "Market": '("stock market" OR "global markets" OR "S&P 500") week',
    "Semiconductors": 'semiconductors (earnings OR chips OR foundry OR memory)',
    "Cloud": '("cloud computing" OR "data center") (AWS OR Azure OR "Google Cloud")',
    "Software": '("enterprise software" OR SaaS OR cybersecurity) (earnings OR products)',
}


CLOUD_COMPANIES = ("AMZN", "MSFT", "GOOGL", "ORCL")


class WeeklyBriefOut(BaseModel):
    market: list[Claim] = Field(default_factory=list, max_length=3)
    semiconductors: list[Claim] = Field(default_factory=list, max_length=3)
    cloud: list[Claim] = Field(default_factory=list, max_length=3)
    software: list[Claim] = Field(default_factory=list, max_length=3)


def completed_week(today: date) -> tuple[date, date]:
    end = today - timedelta(days=today.weekday() + 1)
    return end - timedelta(days=6), end


def filing_source(session, fetcher, topic: str, start: date, end: date) -> Source | None:
    start_at = datetime.combine(start, time.min)
    end_at = datetime.combine(end + timedelta(days=1), time.min)
    query = select(Filing, Universe).join(Universe, Universe.ticker == Filing.ticker).where(
        Universe.active, Filing.form == "8-K", Filing.items.like("%2.02%"),
        Filing.filed_at >= start_at, Filing.filed_at < end_at,
    )
    if topic == "Cloud":
        query = query.where(Universe.ticker.in_(CLOUD_COMPANIES))
    elif topic == "Market":
        query = query.where(Universe.is_demo, Universe.industry.notin_(("Semiconductors", "Software")),
                            Universe.ticker.notin_(CLOUD_COMPANIES))
    else:
        query = query.where(Universe.industry == topic, Universe.ticker.notin_(CLOUD_COMPANIES))
    row = session.execute(query.order_by(Universe.market_cap_rank.asc().nulls_last(), Filing.filed_at.desc()).limit(1)).first()
    if row is None:
        return None
    filing, company = row
    try:
        sections = fetcher.sections(filing.form, filing.items, filing.url)
    except httpx.HTTPError:
        return None
    if not sections:
        return None
    release = sections[0]
    return Source(id=f"F-{topic.lower()}", kind="primary", text=f"{company.name}\n{cap(release.text, 3000)}",
                  url=release.url, label=release.label, outlet="SEC EDGAR", date=filing.filed_at.date().isoformat())


def generate(session, brave, today: date, fetcher=None):
    start, end = completed_week(today)
    key = end.isoformat()
    existing = outputs.latest(session, KIND, key)
    if existing is not None:
        return existing

    outlets = news.load_outlets()
    window = f"{start.isoformat()}to{key}"
    sections = {}
    seen = set()
    sources = []
    for topic, query in TOPICS.items():
        results = news.cached_search(session, brave, query, freshness=window, job=KIND)
        links = [
            link for link in news.coverage_links(results, outlets, limit=16, max_per_outlet=3)
            if link.published and start <= link.published.date() <= end and link.url not in seen
        ][:8]
        seen.update(link.url for link in links)
        topic_sources = sources_from_links(links, start=len(sources) + 1)
        if fetcher and (release := filing_source(session, fetcher, topic, start, end)):
            topic_sources.append(release)
        sections[topic.lower()] = topic_sources
        sources.extend(topic_sources)

    if not sources:
        return None

    def validate(out):
        checked = Checked()
        clean = {}
        for topic, topic_sources in sections.items():
            validator = Validator(topic_sources)
            clean[topic] = validator.claims(topic, getattr(out, topic))
            checked.dropped.extend(validator.checked.dropped)
            checked.cited_ids.update(validator.checked.cited_ids)
        return (WeeklyBriefOut(**clean) if any(clean.values()) else None), checked

    system = prompts.load("weekly_brief").replace("{rules}", prompts.load("rules"))
    material = "\n\n".join(f"{topic}:\n{render_sources(items)}" for topic, items in sections.items())
    return outputs.generate(session, kind=KIND, scope_key=key, job=KIND, task="routine",
                            system=system, user=f"Week {start} through {end}\n\n{material}",
                            output_model=WeeklyBriefOut, sources=sources, validate=validate,
                            extra={"start": start.isoformat(), "end": key}, max_tokens=1600)
