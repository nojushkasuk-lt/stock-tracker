"""Filing-triggered company profiles, written by the profile model (Sonnet).

Inputs: the previous profile (P0), our EDGAR metrics (M1) and sections of the new filing (K1, K2, ...).
`process_queue` works through filings that `data/filings.py` queued (processed_at NULL), only for covered
stocks (followed by someone, or demo: rule 8), newest filing per company.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from tracker.ai import llm, outputs, prompts
from tracker.analysis.metrics import Metrics, compute_metrics
from tracker.data.filing_text import FilingFetcher, Section
from tracker.data.filings import is_profile_trigger
from tracker.data.universe import covered_tickers
from tracker.models import AiOutput, Filing, Fundamental, Universe
from tracker.ai.citations import Checked, Claim, Source, Validator, render_sources

PROFILE_MAX_TOKENS = 16_000  # includes adaptive thinking; a profile itself is about 3-4k tokens
SECTIONS = ("about", "business", "strategy_and_trajectory", "latest_report", "bull_case", "bear_case", "what_to_watch")
REQUIRED = ("about", "business", "bull_case", "bear_case")  # a profile missing one of these is rejected


class Point(BaseModel):
    title: str
    text: str
    source_ids: list[str]


class ProfileOut(BaseModel):
    about: list[Claim] = Field(default_factory=list)
    business: list[Point] = Field(default_factory=list)
    strategy_and_trajectory: list[Point] = Field(default_factory=list)
    latest_report: list[Point] = Field(default_factory=list)
    bull_case: list[Point] = Field(default_factory=list)
    bear_case: list[Point] = Field(default_factory=list)
    what_to_watch: list[Point] = Field(default_factory=list)
    what_changed: str = ""


def system_prompt() -> str:
    return prompts.load("profile").replace("{rules}", prompts.load("rules"))


def user_prompt(company: str, ticker: str, filing: str, sources: list[Source]) -> str:
    return f"Company: {company} ({ticker}). New filing: {filing}.\n\nSources:\n{render_sources(sources)}"


def _check_points(v: Validator, where: str, points: list[Point]) -> list[Point]:
    """A point is checked as one claim (title and text together), so numbers in the title are checked too."""
    kept = []
    for p in points:
        if v.claims(where, [Claim(text=f"{p.title}. {p.text}", source_ids=p.source_ids)]):
            kept.append(p)
    return kept


def validate(out: ProfileOut, sources: list[Source]) -> tuple[ProfileOut | None, Checked]:
    """Drop bad claims. None if a required section ends up empty (the old profile stays in place)."""
    v = Validator(sources)
    kept: dict = {"about": v.claims("about", out.about)}
    for name in SECTIONS[1:]:
        kept[name] = _check_points(v, name, getattr(out, name))
    what_changed = v.free_text("what_changed", out.what_changed, firm_allowed=True) or ""
    if any(not kept[name] for name in REQUIRED):
        return None, v.checked
    return ProfileOut(**kept, what_changed=what_changed), v.checked


# ---- sources --------------------------------------------------------------------------------------

def _money(v: float) -> str:
    sign = "-" if v < 0 else ""
    v = abs(v)
    if v >= 1e9:
        return f"{sign}${v / 1e9:.1f}B"
    return f"{sign}${v / 1e6:.0f}M"


def metrics_text(m: Metrics) -> str | None:
    parts = []
    if m.revenue_ttm is not None:
        parts.append(f"revenue TTM {_money(m.revenue_ttm)}")
    if m.revenue_growth_yoy is not None:
        parts.append(f"revenue growth YoY {m.revenue_growth_yoy * 100:.1f}%")
    if m.operating_margin is not None:
        parts.append(f"operating margin {m.operating_margin * 100:.1f}%")
    if m.net_margin is not None:
        parts.append(f"net margin {m.net_margin * 100:.1f}%")
    if m.eps_diluted_ttm is not None:
        parts.append(f"diluted EPS TTM ${m.eps_diluted_ttm:.2f}")
    if m.net_debt_to_ebitda is not None:
        parts.append(f"net debt/EBITDA {m.net_debt_to_ebitda:.1f}x" + (" (net cash)" if m.net_debt_to_ebitda < 0 else ""))
    if not parts:
        return None
    as_of = f" (as of {m.as_of.isoformat()})" if m.as_of else ""
    return "Computed from SEC filings" + as_of + ": " + "; ".join(parts) + "."


def previous_text(row: AiOutput) -> str:
    c = row.content
    lines = []
    for name in (*SECTIONS, "overview"):  # "overview" was the first section before profile version 2
        items = c.get(name, [])
        if items:
            lines.append(f"{name}: " + " ".join((f"{x['title']}: " if x.get("title") else "") + x["text"] for x in items))
    return "\n".join(lines)


def build_sources(prev: AiOutput | None, metrics: Metrics | None, sections: list[Section],
                  reference: tuple[str, str] | None = None) -> list[Source]:
    """reference = (article text, url): the company's Wikipedia lead and history."""
    sources = []
    if prev is not None:
        sources.append(Source(id="P0", kind="own", text=previous_text(prev), label="previous profile",
                              date=prev.created_at.date().isoformat()))
    mt = metrics_text(metrics) if metrics else None
    if mt:
        sources.append(Source(id="M1", kind="metrics", text=mt, label="our metrics"))
    for i, sec in enumerate(sections, 1):
        sources.append(Source(id=f"K{i}", kind="primary", text=sec.text, label=sec.label, url=sec.url,
                              outlet="SEC EDGAR"))
    if reference:
        sources.append(Source(id="W1", kind="reference", text=reference[0], label="Wikipedia article (lead and history)",
                              url=reference[1], outlet="Wikipedia"))
    return sources


def _reference(session: Session, ticker: str) -> tuple[str, str] | None:
    from tracker.data import wikipedia
    from tracker.models import CompanyFacts

    facts = session.get(CompanyFacts, ticker)
    if facts is None or not facts.wikipedia_url:
        return None
    try:
        text = wikipedia.fetch(facts.wikipedia_url)
    except Exception:
        return None  # the profile is still written from the filing
    return (text, facts.wikipedia_url) if text else None


# ---- generation -----------------------------------------------------------------------------------

def filing_label(f: Filing) -> str:
    base = f"{f.form} filed {f.filed_at.date().isoformat()}"
    return base + (f" for the period ending {f.period_end.isoformat()}" if f.period_end else "")


def write_profile(session: Session, f: Filing, fetcher: FilingFetcher, *, client=None, now: datetime | None = None,
                  reference: tuple[str, str] | None = None):
    """Generate (or reuse) the profile after filing f. None if the filing had no usable sections or the output
    was rejected; the previous profile then stays in place."""
    u = session.get(Universe, f.ticker)
    sections = fetcher.sections(f.form, f.items, f.url)
    if not sections:
        return None
    rows = list(session.scalars(select(Fundamental).where(Fundamental.ticker == f.ticker)))
    metrics = compute_metrics(rows, u.industry) if rows else None
    prev = outputs.latest(session, "profile", f.ticker)
    sources = build_sources(prev, metrics, sections, reference=reference if reference is not None else _reference(session, f.ticker))
    return outputs.generate(
        session, kind="profile", scope_key=f.ticker, job="profiles", task="profile", system=system_prompt(),
        user=user_prompt(u.name, u.ticker, filing_label(f), sources), output_model=ProfileOut, sources=sources,
        validate=lambda out: validate(out, sources), max_tokens=PROFILE_MAX_TOKENS, client=client, now=now)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def process_queue(session: Session, fetcher: FilingFetcher, *, client=None, limit: int | None = None,
                  now: datetime | None = None) -> dict[str, str]:
    """Update profiles for queued filings. Returns {ticker: outcome}. Stops at the budget; a stock nobody
    covers keeps its newest filing queued, so a profile is written once someone follows it."""
    now = now or _now()
    covered = covered_tickers(session)
    queued = [f for f in session.scalars(select(Filing).where(Filing.processed_at.is_(None))
                                         .order_by(Filing.filed_at.desc()))
              if is_profile_trigger(f.form, f.items)]
    newest: dict[str, Filing] = {}
    for f in queued:
        if f.ticker in newest:
            f.processed_at = now  # superseded by a newer filing for the same company
        else:
            newest[f.ticker] = f
    results: dict[str, str] = {}
    for ticker, f in newest.items():
        if ticker not in covered:
            continue
        if limit is not None and len(results) >= limit:
            break
        try:
            row = write_profile(session, f, fetcher, client=client, now=now)
        except (llm.BudgetExceeded, llm.LLMUnavailable) as e:
            results[ticker] = f"stopped: {e}"
            break
        except llm.LLMError as e:  # too large, refused, truncated: retrying would fail (and cost) the same way
            f.processed_at = now
            results[ticker] = f"skipped: {e}"
            continue
        except Exception as e:  # network or EDGAR errors: try again next run
            results[ticker] = f"error: {type(e).__name__}: {e}"
            continue
        f.processed_at = now
        results[ticker] = f"profile {row.id}" if row is not None else "no profile (no sections or rejected)"
    session.flush()
    return results


# ---- first profiles for every stock, through the Batch API ------------------------------------------------

CONTEXT_CAPS = {"business": 20_000, "risk_factors": 15_000}  # 10-K context sent next to a newer 10-Q


def _latest(session: Session, ticker: str, forms: tuple[str, ...]) -> Filing | None:
    return session.scalars(select(Filing).where(Filing.ticker == ticker, Filing.form.in_(forms))
                           .order_by(Filing.filed_at.desc())).first()


def initial_sections(fetcher: FilingFetcher, latest: Filing, annual: Filing | None) -> list[Section]:
    """The latest periodic report; when it is a 10-Q, also the last 10-K's Business and Risk Factors (shortened),
    since a 10-Q has no business description."""
    from tracker.data.filing_text import cap

    secs = fetcher.sections(latest.form, latest.items, latest.url)
    if not secs and latest.form == "10-Q" and annual is not None:
        return fetcher.sections(annual.form, annual.items, annual.url)  # 10-Q layout we could not split: use the 10-K
    if latest.form == "10-Q" and annual is not None:
        for sec in fetcher.sections(annual.form, annual.items, annual.url):
            if sec.key in CONTEXT_CAPS:
                secs.append(Section(sec.key, sec.label + f" (filed {annual.filed_at.date().isoformat()})",
                                    cap(sec.text, CONTEXT_CAPS[sec.key]), sec.url))
    return secs


def needs_first_profile(session: Session, ticker: str) -> bool:
    """No profile yet, or only a version-1 profile (before about / titled points)."""
    row = outputs.latest(session, "profile", ticker)
    return row is None or "about" not in row.content


def model_for_rank(rank: int | None, sonnet_top: int) -> str:
    from tracker import config

    return config.MODEL_PROFILE if rank is not None and rank <= sonnet_top else config.MODEL_ROUTINE


def submit_first_profiles(session: Session, fetcher: FilingFetcher, *, sonnet_top: int = 30, tickers: list[str] | None = None,
                          force: bool = False, client=None, now: datetime | None = None, log=print) -> str | None:
    """One batch with a first (version-2) profile for every active stock that lacks one: the top `sonnet_top` by
    market cap on the profile model (Sonnet), the rest on the routine model (Haiku). Returns the batch id."""
    from tracker.models import AiBatch

    now = now or _now()
    q = select(Universe).where(Universe.active).order_by(Universe.market_cap_rank)
    if tickers:
        q = select(Universe).where(Universe.ticker.in_([t.upper() for t in tickers]))
    reqs, items = [], {}
    for u in session.scalars(q):
        if not force and not needs_first_profile(session, u.ticker):
            continue
        latest = _latest(session, u.ticker, ("10-K", "10-Q"))
        if latest is None:
            log(f"{u.ticker}: no 10-K or 10-Q on record, skipped")
            continue
        try:
            sections = initial_sections(fetcher, latest, _latest(session, u.ticker, ("10-K",)))
        except Exception as e:
            log(f"{u.ticker}: could not read the filing ({type(e).__name__}), skipped")
            continue
        if not sections:
            log(f"{u.ticker}: no usable sections in {latest.form}, skipped")
            continue
        rows = list(session.scalars(select(Fundamental).where(Fundamental.ticker == u.ticker)))
        metrics = compute_metrics(rows, u.industry) if rows else None
        prev = outputs.latest(session, "profile", u.ticker) if force else None
        sources = build_sources(prev, metrics, sections, reference=_reference(session, u.ticker))
        model = model_for_rank(u.market_cap_rank, sonnet_top)
        if sections and sections[0].url != latest.url:  # fell back to the 10-K
            latest = _latest(session, u.ticker, ("10-K",)) or latest
        system, user = system_prompt(), user_prompt(u.name, u.ticker, filing_label(latest), sources)
        reqs.append(llm.BatchRequest(custom_id=u.ticker.replace(".", "_"), system=system, user=user, model=model))
        items[u.ticker.replace(".", "_")] = {"scope_key": u.ticker, "model": model, "filing": latest.accession,
                                            "input_hash": outputs.input_hash(model, system, user, ProfileOut),
                                            "sources": [x.model_dump() for x in sources]}
        log(f"{u.ticker}: {model.split('-')[1]}, {latest.form} {latest.filed_at.date()}, {len(sections)} sections")
    if not reqs:
        return None
    batch_id, skipped = llm.submit_batch(session, task="profile", requests=reqs, output_model=ProfileOut,
                                         max_tokens=PROFILE_MAX_TOKENS, client=client, now=now)
    for cid, why in skipped.items():
        log(f"{cid}: left out ({why})")
        items.pop(cid, None)
    if batch_id:
        for r in reqs:
            if r.custom_id in items:
                items[r.custom_id]["prompt_tokens"] = r.prompt_tokens
        session.add(AiBatch(id=batch_id, job="profiles", kind="profile", created_at=now, collected_at=None, items=items))
        session.flush()
    return batch_id


def collect_profiles(session: Session, batch_id: str, *, client=None, now: datetime | None = None, log=print) -> dict[str, str]:
    """Validate and save the results of an ended profile batch. Returns {ticker: outcome}."""
    from tracker.ai.citations import Source
    from tracker.models import AiBatch

    now = now or _now()
    b = session.get(AiBatch, batch_id)
    if b is None or b.collected_at is not None:
        return {}
    status, counts = llm.batch_status(batch_id, client)
    if status != "ended":
        log(f"batch {batch_id}: {status} {counts}")
        return {}
    results = llm.collect_batch(session, batch_id, job="profiles", output_model=ProfileOut,
                                max_tokens=PROFILE_MAX_TOKENS, client=client, now=now)
    outcomes: dict[str, str] = {}
    for cid, item in b.items.items():
        ticker, res = item["scope_key"], results.get(cid)
        if res is None or isinstance(res, llm.LLMError):
            outcomes[ticker] = f"failed: {res}"
            continue
        sources = [Source(**x) for x in item["sources"]]
        row = outputs.save(session, kind="profile", scope_key=ticker, input_hash_=item["input_hash"], result=res,
                           sources=sources, validate=lambda out, src=sources: validate(out, src), now=now)
        if row is None:
            outcomes[ticker] = "rejected by validation (a required section was empty)"
            continue
        f = session.get(Filing, item.get("filing"))
        if f is not None and f.processed_at is None:
            f.processed_at = now
        dropped = len(row.content.get("dropped", []))
        outcomes[ticker] = f"saved ({res.model.split('-')[1]}, ${res.cost_usd:.3f}, {dropped} claims dropped)"
    b.collected_at = now
    b.items = {cid: {"scope_key": it["scope_key"], "model": it["model"]} for cid, it in b.items.items()}  # drop source text
    session.flush()
    return outcomes


def upgrade_targets(session: Session) -> list[str]:
    """Covered stocks (someone follows them, or demo) whose current profile came from the routine model:
    they get a profile-model version in the next batch."""
    from tracker import config

    out = []
    for t in sorted(covered_tickers(session)):
        row = outputs.latest(session, "profile", t)
        if row is not None and row.model != config.MODEL_PROFILE:
            out.append(t)
    return out
