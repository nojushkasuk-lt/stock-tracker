from dataclasses import dataclass
from datetime import date

import pytest

from tracker.analysis.metrics import annual_history, build_series, compute_metrics, ttm


@dataclass
class R:
    metric: str
    period_end: date
    duration_days: int
    value: float
    filed_at: date = date(2026, 1, 1)


def D(s):
    return date.fromisoformat(s)


def flow(tag, start, end, value, filed="2026-01-01"):
    return R(tag, D(end), (D(end) - D(start)).days, value, D(filed))


def inst(tag, end, value, filed="2026-01-01"):
    return R(tag, D(end), 0, value, D(filed))


REV = "RevenueFromContractWithCustomerExcludingAssessedTax"


def company():
    """FY ends Dec 31. FY2024 and FY2025 reported; Q3 2026 10-Q gives 9-month YTD (and the 2025 comparison)."""
    r = []
    r += [flow(REV, "2024-01-01", "2024-12-31", 1000), flow(REV, "2025-01-01", "2025-12-31", 1200)]
    r += [flow(REV, "2025-01-01", "2025-09-30", 880), flow(REV, "2026-01-01", "2026-09-30", 1050)]
    r += [flow(REV, "2024-01-01", "2024-09-30", 740)]
    r += [flow(REV, "2026-07-01", "2026-09-30", 380)]  # 3-month fact must not be mistaken for YTD
    r += [flow("OperatingIncomeLoss", "2025-01-01", "2025-12-31", 240), flow("OperatingIncomeLoss", "2025-01-01", "2025-09-30", 170),
          flow("OperatingIncomeLoss", "2026-01-01", "2026-09-30", 230)]
    r += [flow("NetIncomeLoss", "2025-01-01", "2025-12-31", 180), flow("NetIncomeLoss", "2025-01-01", "2025-09-30", 130),
          flow("NetIncomeLoss", "2026-01-01", "2026-09-30", 170)]
    r += [flow("EarningsPerShareDiluted", "2025-01-01", "2025-12-31", 1.8), flow("EarningsPerShareDiluted", "2025-01-01", "2025-09-30", 1.3),
          flow("EarningsPerShareDiluted", "2026-01-01", "2026-09-30", 1.7)]
    r += [flow("DepreciationDepletionAndAmortization", "2025-01-01", "2025-12-31", 40), flow("DepreciationDepletionAndAmortization", "2025-01-01", "2025-09-30", 30),
          flow("DepreciationDepletionAndAmortization", "2026-01-01", "2026-09-30", 36)]
    r += [inst("CashAndCashEquivalentsAtCarryingValue", "2026-09-30", 100), inst("MarketableSecuritiesCurrent", "2026-09-30", 50),
          inst("LongTermDebt", "2026-09-30", 400), inst("CommercialPaper", "2026-09-30", 30)]
    return r


def test_ttm_is_last_year_plus_ytd_minus_prior_ytd():
    s = build_series(company(), "revenue")
    value, end = ttm(s)
    assert end == D("2026-09-30")
    assert value == 1200 + 1050 - 880  # 1370


def test_ttm_equals_the_annual_figure_when_the_latest_report_is_a_10k():
    rows = [r for r in company() if r.period_end <= D("2025-12-31")]
    assert ttm(build_series(rows, "revenue")) == (1200, D("2025-12-31"))


def test_ttm_is_none_when_the_prior_year_comparison_is_missing():
    rows = [r for r in company() if not (r.metric == REV and r.period_end == D("2025-09-30"))]
    assert ttm(build_series(rows, "revenue")) is None


def test_metrics_all_ratios():
    m = compute_metrics(company(), industry="Technology Hardware")
    assert m.as_of == D("2026-09-30")
    assert m.revenue_ttm == 1370
    assert m.operating_income_ttm == 240 + 230 - 170  # 300
    assert m.operating_margin == pytest.approx(300 / 1370)
    assert m.net_income_ttm == 180 + 170 - 130  # 220
    assert m.net_margin == pytest.approx(220 / 1370)
    assert m.eps_diluted_ttm == pytest.approx(1.8 + 1.7 - 1.3)
    # growth: TTM at Sep 2026 (1370) vs TTM at Sep 2025 = FY2024 + YTD25 - YTD24 = 1000 + 880 - 740 = 1140
    assert m.revenue_growth_yoy == pytest.approx(1370 / 1140 - 1)
    assert m.ebitda_ttm == 300 + (40 + 36 - 30)  # 346
    assert m.net_debt == 400 + 30 - (100 + 50)  # 280
    assert m.net_debt_to_ebitda == pytest.approx(280 / 346)


def test_tag_change_over_time_is_merged_and_priority_wins_per_period():
    rows = [flow("SalesRevenueNet", "2020-01-01", "2020-12-31", 500),
            flow(REV, "2021-01-01", "2021-12-31", 600),
            flow("Revenues", "2021-01-01", "2021-12-31", 650)]  # higher-priority tag for the same period
    s = build_series(rows, "revenue")
    assert [f.value for f in s] == [500, 650]


def test_restated_period_uses_the_latest_filing():
    rows = [flow(REV, "2025-01-01", "2025-12-31", 1000, filed="2026-02-01"),
            flow(REV, "2025-01-01", "2025-12-31", 1010, filed="2027-02-01")]
    assert build_series(rows, "revenue")[0].value == 1010


def test_52_53_week_year_ends_still_match():
    rows = [flow(REV, "2024-09-29", "2025-09-27", 1000), flow(REV, "2025-09-28", "2026-06-27", 800),
            flow(REV, "2024-09-29", "2025-06-28", 750)]
    value, end = ttm(build_series(rows, "revenue"))
    assert (value, end) == (1000 + 800 - 750, D("2026-06-27"))


def test_net_debt_not_applicable_for_banks_but_margins_still_computed():
    m = compute_metrics(company(), industry="Banks")
    assert m.net_debt_to_ebitda is None and "banks" in m.notes["net_debt_to_ebitda"].lower()
    assert m.net_margin is not None


def test_missing_da_gives_a_note_not_a_number():
    rows = [r for r in company() if r.metric != "DepreciationDepletionAndAmortization"]
    m = compute_metrics(rows, industry="Software")
    assert m.net_debt_to_ebitda is None and "Depreciation" in m.notes["net_debt_to_ebitda"]
    assert m.net_debt == 280  # net debt itself is still reported


def test_negative_ebitda_is_not_meaningful():
    rows = [r for r in company() if r.metric != "OperatingIncomeLoss"]
    rows += [flow("OperatingIncomeLoss", "2025-01-01", "2025-12-31", -500), flow("OperatingIncomeLoss", "2025-01-01", "2025-09-30", -400),
             flow("OperatingIncomeLoss", "2026-01-01", "2026-09-30", -450)]
    m = compute_metrics(rows, industry="Aerospace & Defense")
    assert m.operating_margin < 0 and m.net_debt_to_ebitda is None and "negative" in m.notes["net_debt_to_ebitda"]


def test_net_debt_falls_back_to_noncurrent_plus_current_debt():
    rows = [r for r in company() if r.metric != "LongTermDebt"]
    rows += [inst("LongTermDebtNoncurrent", "2026-09-30", 350), inst("LongTermDebtCurrent", "2026-09-30", 50)]
    assert compute_metrics(rows, industry="Software").net_debt == 350 + 50 + 30 - 150


def test_company_with_no_revenue_data_returns_empty_metrics_with_a_note():
    m = compute_metrics([], industry="Software")
    assert m.revenue_ttm is None and m.as_of is None and "revenue" in m.notes


def test_annual_history_for_the_chart():
    h = annual_history(company())
    assert [p.year_end for p in h] == [D("2024-12-31"), D("2025-12-31")]
    assert h[1].revenue == 1200 and h[1].margin == pytest.approx(240 / 1200) and h[1].margin_kind == "operating"
    assert h[0].margin is None  # no 2024 operating or net income in the fixture


def test_da_fallback_uses_depreciation_plus_intangible_amortization_and_says_so():
    rows = [r for r in company() if r.metric != "DepreciationDepletionAndAmortization"]
    for tag, (a, y1, y0) in {"Depreciation": (30, 22, 20), "AmortizationOfIntangibleAssets": (10, 8, 7)}.items():
        rows += [flow(tag, "2025-01-01", "2025-12-31", a), flow(tag, "2026-01-01", "2026-09-30", y1), flow(tag, "2025-01-01", "2025-09-30", y0)]
    m = compute_metrics(rows, industry="Software")
    assert m.ebitda_basis == "approx"
    assert m.ebitda_ttm == 300 + (30 + 22 - 20) + (10 + 8 - 7)  # 343
    assert compute_metrics(company(), industry="Software").ebitda_basis == "reported"


def test_depreciation_alone_is_not_enough():
    rows = [r for r in company() if r.metric != "DepreciationDepletionAndAmortization"]
    rows += [flow("Depreciation", "2025-01-01", "2025-12-31", 30), flow("Depreciation", "2026-01-01", "2026-09-30", 22),
             flow("Depreciation", "2025-01-01", "2025-09-30", 20)]
    m = compute_metrics(rows, industry="Software")
    assert m.ebitda_ttm is None and m.net_debt_to_ebitda is None


def test_a_company_that_never_reports_debt_is_net_cash():
    rows = [r for r in company() if r.metric not in ("LongTermDebt", "CommercialPaper")]
    m = compute_metrics(rows, industry="Software")
    assert m.net_debt == -(100 + 50)
    assert m.net_debt_to_ebitda == pytest.approx(-150 / 346)
