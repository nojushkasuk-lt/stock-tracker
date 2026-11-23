import math

import pytest

from tracker.analysis import performance as p


def test_compound_is_not_a_sum():
    assert p.compound([10, -10]) == pytest.approx(-1.0)
    assert p.compound([]) == 0.0


def test_ranges_leave_out_ranges_without_enough_history():
    out = {r.label: r for r in p.ranges([1.0] * 30)}
    assert set(out) == {"1D", "1W", "1M"}
    assert out["1D"].pct == pytest.approx(1.0)
    assert out["1W"].pct == pytest.approx((1.01 ** 5 - 1) * 100)


def test_risk_stats():
    r = [1.0, -2.0] * 15
    k = p.risk(r, index_pct=[x / 2 for x in r])
    assert k.beta == pytest.approx(2.0)
    assert k.best_day_pct == 1.0 and k.worst_day_pct == -2.0
    assert k.max_drawdown_pct < 0
    assert k.volatility_pct == pytest.approx(statistics_stdev(r) * math.sqrt(252))


def statistics_stdev(xs):
    import statistics
    return statistics.stdev(xs)


def test_drawdown_measures_peak_to_trough():
    k = p.risk([10.0] + [0.0] * 10 + [-50.0] + [0.0] * 10)
    assert k.max_drawdown_pct == pytest.approx(-50.0)


def test_risk_needs_twenty_days_and_beta_needs_aligned_index():
    assert p.risk([1.0] * 10) is None
    assert p.risk([1.0, 2.0] * 15, index_pct=[1.0] * 5).beta is None


def test_svg_points_span_the_box():
    pts = p.svg_points([1.0, 2.0, 1.5]).split()
    assert pts[0] == "0,240" and pts[1] == "500,10" and pts[-1].startswith("1000,")
