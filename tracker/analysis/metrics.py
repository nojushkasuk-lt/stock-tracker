"""Ratios from EDGAR figures (AGENTS.md rule 3: numbers are computed here, never by the model).

Pure functions on plain facts. A "concept" (revenue, cash, ...) can be reported under several XBRL tags over the
years; `build_series` merges them by priority. Anything that cannot be computed honestly is None, never a guess.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable

# Ordered by priority: the first tag that has a value for a period wins.
CONCEPTS: dict[str, list[str]] = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "eps_diluted": ["EarningsPerShareDiluted", "IncomeLossFromContinuingOperationsPerDilutedShare"],
    "da": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "DepreciationAmortizationAndAccretionNet"],
    # Fallback when there is no single D&A total: depreciation plus amortization of intangibles (both required).
    "depreciation": ["Depreciation"],
    "amortization_intangibles": ["AmortizationOfIntangibleAssets"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "short_term_investments": ["MarketableSecuritiesCurrent", "ShortTermInvestments"],
    "debt_total": ["LongTermDebt", "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities"],
    "debt_noncurrent": ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"],
    "debt_current": ["LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent", "DebtCurrent"],
    "short_borrowings": ["ShortTermBorrowings", "CommercialPaper"],
}
ALL_TAGS = sorted({t for tags in CONCEPTS.values() for t in tags})

# Industries where operating income / net debt are not comparable (see AGENTS.md universe labels).
NET_DEBT_NOT_APPLICABLE = {"Banks", "Capital Markets", "Insurance", "Payments"}
NET_DEBT_NA_NOTE = "Not meaningful for banks, insurers, brokers and payment networks."

ANNUAL = (350, 380)  # days
TOL_END = 10  # days: 52/53-week fiscal years shift period ends


@dataclass(frozen=True)
class Fact:
    start: date | None  # None = point in time
    end: date
    value: float
    filed: date


def build_series(rows: Iterable, concept: str) -> list[Fact]:
    """Merge the tags of one concept. `rows` need .metric, .period_end, .duration_days, .value, .filed_at."""
    rank = {t: i for i, t in enumerate(CONCEPTS[concept])}
    best: dict[tuple, tuple] = {}
    for r in rows:
        if r.metric not in rank:
            continue
        start = r.period_end - timedelta(days=r.duration_days) if r.duration_days else None
        key = (start, r.period_end)
        cand = (rank[r.metric], -r.filed_at.toordinal(), Fact(start, r.period_end, float(r.value), r.filed_at))
        if key not in best or cand[:2] < best[key][:2]:
            best[key] = cand
    return sorted((v[2] for v in best.values()), key=lambda f: f.end)


def _days(a: date, b: date) -> int:
    return abs((a - b).days)


def _is_annual(f: Fact) -> bool:
    return f.start is not None and ANNUAL[0] <= (f.end - f.start).days <= ANNUAL[1]


def ttm(series: list[Fact], as_of: date | None = None) -> tuple[float, date] | None:
    """Trailing twelve months ending near `as_of` (default: the latest period): last full year + this year's
    year-to-date - the same year-to-date a year earlier. Returns (value, period_end) or None."""
    flows = [f for f in series if f.start is not None]
    if not flows:
        return None
    as_of = as_of or max(f.end for f in flows)
    annuals = [f for f in flows if _is_annual(f) and f.end <= as_of + timedelta(days=TOL_END)]
    if not annuals:
        return None
    a = max(annuals, key=lambda f: f.end)
    if _days(a.end, as_of) <= TOL_END:
        return a.value, a.end
    ytd = [f for f in flows if 0 <= (f.start - a.end).days <= 3 and _days(f.end, as_of) <= TOL_END and not _is_annual(f)]
    if not ytd:
        return None
    y1 = max(ytd, key=lambda f: f.end)
    prior = [
        f for f in flows
        if _days(f.start, a.start) <= TOL_END and _days(f.end, y1.end - timedelta(days=364)) <= TOL_END + 4
    ]
    if not prior:
        return None
    y0 = min(prior, key=lambda f: _days(f.end, y1.end - timedelta(days=364)))
    return a.value + y1.value - y0.value, y1.end


def instant_at(series: list[Fact], end: date, tol: int = 5) -> float | None:
    hits = [f for f in series if f.start is None and _days(f.end, end) <= tol]
    return max(hits, key=lambda f: f.end).value if hits else None


def latest_instant_end(series: list[Fact]) -> date | None:
    ends = [f.end for f in series if f.start is None]
    return max(ends) if ends else None


@dataclass
class Metrics:
    as_of: date | None = None
    revenue_ttm: float | None = None
    operating_income_ttm: float | None = None
    net_income_ttm: float | None = None
    operating_margin: float | None = None  # fraction, 0.31 = 31%
    net_margin: float | None = None
    revenue_growth_yoy: float | None = None
    eps_diluted_ttm: float | None = None
    ebitda_ttm: float | None = None
    net_debt: float | None = None
    net_debt_to_ebitda: float | None = None
    ebitda_basis: str | None = None  # "reported" or "approx" (depreciation + intangible amortization)
    notes: dict[str, str] = field(default_factory=dict)  # metric -> why it is not available


def net_debt_at(series_by_concept: dict[str, list[Fact]]) -> float | None:
    """Total debt (incl. commercial paper / short borrowings) minus cash and short-term investments."""
    cash_s = series_by_concept.get("cash", [])
    b = latest_instant_end(cash_s)
    if b is None:
        return None
    cash = instant_at(cash_s, b)
    if cash is None:
        return None
    cash += instant_at(series_by_concept.get("short_term_investments", []), b) or 0.0
    short = instant_at(series_by_concept.get("short_borrowings", []), b) or 0.0
    total = instant_at(series_by_concept.get("debt_total", []), b)
    if total is None:
        nc = instant_at(series_by_concept.get("debt_noncurrent", []), b)
        if nc is None:
            # A company that has never tagged any debt is treated as debt-free (net cash).
            debt_concepts = ("debt_total", "debt_noncurrent", "debt_current", "short_borrowings")
            return -cash + short if not any(series_by_concept.get(c) for c in debt_concepts[:3]) else None
        total = nc + (instant_at(series_by_concept.get("debt_current", []), b) or 0.0)
    return total + short - cash


def compute_metrics(rows: list, industry: str | None = None) -> Metrics:
    rows = list(rows)
    s = {c: build_series(rows, c) for c in CONCEPTS}
    m = Metrics()

    rev = ttm(s["revenue"])
    if rev is None:
        m.notes["revenue"] = "Not enough reported history yet (needs a full fiscal year and the matching quarters)."
        return m
    m.revenue_ttm, m.as_of = rev

    # Same trailing period for everything that is a flow, so the ratios line up.
    def flow(concept: str, as_of: date | None = None) -> float | None:
        r = ttm(s[concept], as_of or m.as_of)
        return r[0] if r else None

    m.operating_income_ttm = flow("operating_income")
    m.net_income_ttm = flow("net_income")
    m.eps_diluted_ttm = flow("eps_diluted")
    if m.revenue_ttm:
        if m.operating_income_ttm is not None:
            m.operating_margin = m.operating_income_ttm / m.revenue_ttm
        else:
            m.notes["operating_margin"] = "No operating income reported (typical for banks and insurers)."
        if m.net_income_ttm is not None:
            m.net_margin = m.net_income_ttm / m.revenue_ttm

    prior = ttm(s["revenue"], m.as_of - timedelta(days=365))
    if prior and prior[0] > 0:
        m.revenue_growth_yoy = m.revenue_ttm / prior[0] - 1
    else:
        m.notes["revenue_growth_yoy"] = "Needs two years of reported revenue."

    if industry in NET_DEBT_NOT_APPLICABLE:
        m.notes["net_debt_to_ebitda"] = NET_DEBT_NA_NOTE
        return m
    da = flow("da")
    m.ebitda_basis = "reported" if da is not None else None
    if da is None:
        dep, amort = flow("depreciation"), flow("amortization_intangibles")
        if dep is not None and amort is not None:
            da, m.ebitda_basis = dep + amort, "approx"
    m.net_debt = net_debt_at(s)
    if m.operating_income_ttm is not None and da is not None:
        m.ebitda_ttm = m.operating_income_ttm + da
    if m.operating_income_ttm is None:
        m.ebitda_basis = None
    if m.net_debt is None:
        m.notes["net_debt_to_ebitda"] = "Debt or cash figures are not available in a comparable form."
    elif m.ebitda_ttm is None:
        m.notes["net_debt_to_ebitda"] = "Depreciation and amortization are not reported under a standard tag."
    elif m.ebitda_ttm <= 0:
        m.notes["net_debt_to_ebitda"] = "Not meaningful: EBITDA is zero or negative."
    else:
        m.net_debt_to_ebitda = m.net_debt / m.ebitda_ttm
    return m


@dataclass(frozen=True)
class AnnualPoint:
    year_end: date
    revenue: float
    margin: float | None  # operating margin, else net margin, else None
    margin_kind: str | None  # "operating" or "net"


def annual_history(rows: list, years: int = 8) -> list[AnnualPoint]:
    """Full fiscal years for the revenue / margin chart, oldest first."""
    rows = list(rows)
    rev = [f for f in build_series(rows, "revenue") if _is_annual(f)]
    op = {f.end: f for f in build_series(rows, "operating_income") if _is_annual(f)}
    ni = {f.end: f for f in build_series(rows, "net_income") if _is_annual(f)}

    def near(d: dict, end: date) -> Fact | None:
        return next((f for e, f in d.items() if _days(e, end) <= TOL_END), None)

    out = []
    for f in rev[-years:]:
        if f.value <= 0:
            continue
        o, n = near(op, f.end), near(ni, f.end)
        if o is not None:
            out.append(AnnualPoint(f.end, f.value, o.value / f.value, "operating"))
        elif n is not None:
            out.append(AnnualPoint(f.end, f.value, n.value / f.value, "net"))
        else:
            out.append(AnnualPoint(f.end, f.value, None, None))
    return out
