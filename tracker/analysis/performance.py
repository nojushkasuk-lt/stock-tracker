"""Performance and risk from stored daily percent changes only (no prices are stored, AGENTS.md rule 13).

A range's performance compounds the daily changes: (1 + r1) * (1 + r2) * ... - 1.
"""

import math
import statistics
from dataclasses import dataclass

TRADING_DAYS = 252
RANGES = [("1D", 1), ("1W", 5), ("1M", 21), ("6M", 126), ("1Y", 252), ("5Y", 1260)]


def compound(returns_pct: list[float]) -> float:
    level = 1.0
    for r in returns_pct:
        level *= 1 + r / 100
    return (level - 1) * 100


def index_line(returns_pct: list[float]) -> list[float]:
    """Growth of 1 over the period, starting at 1.0 (one more point than returns)."""
    out = [1.0]
    for r in returns_pct:
        out.append(out[-1] * (1 + r / 100))
    return out


@dataclass(frozen=True)
class RangePerf:
    label: str
    pct: float
    days: int  # trading days actually covered (less than asked when history is short)


def ranges(returns_pct: list[float]) -> list[RangePerf]:
    """Returns oldest first. A range is left out when there is less than 90% of its history."""
    out = []
    for label, n in RANGES:
        if len(returns_pct) >= max(1, int(n * 0.9)):
            seg = returns_pct[-n:]
            out.append(RangePerf(label, compound(seg), len(seg)))
    return out


@dataclass(frozen=True)
class Risk:
    days: int
    volatility_pct: float       # annualised standard deviation of daily changes
    beta: float | None          # vs the index, None without index data
    max_drawdown_pct: float     # largest peak-to-trough fall, negative
    best_day_pct: float
    worst_day_pct: float


def risk(returns_pct: list[float], index_pct: list[float] | None = None, days: int = TRADING_DAYS) -> Risk | None:
    """Last `days` trading days. index_pct must be aligned day by day with returns_pct (same dates)."""
    r = returns_pct[-days:]
    if len(r) < 20:
        return None
    vol = statistics.stdev(r) * math.sqrt(TRADING_DAYS)
    beta = None
    if index_pct is not None:
        m = index_pct[-days:]
        if len(m) == len(r) and statistics.variance(m) > 0:
            mr, mm = statistics.mean(r), statistics.mean(m)
            cov = sum((a - mr) * (b - mm) for a, b in zip(r, m)) / (len(r) - 1)
            beta = cov / statistics.variance(m)
    peak, mdd = 1.0, 0.0
    for level in index_line(r):
        peak = max(peak, level)
        mdd = min(mdd, level / peak - 1)
    return Risk(len(r), vol, beta, mdd * 100, max(r), min(r))


def svg_points(levels: list[float], width: int = 1000, height: int = 250, pad: int = 10, max_points: int = 120) -> str:
    """Polyline points for a growth line, scaled to the box (top = highest)."""
    if len(levels) < 2:
        return f"0,{height / 2:.0f} {width},{height / 2:.0f}"
    step = max(1, math.ceil(len(levels) / max_points))
    pts = levels[::step]
    if pts[-1] != levels[-1]:
        pts.append(levels[-1])
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or 1.0
    n = len(pts) - 1
    return " ".join(f"{i * width / n:.0f},{pad + (hi - p) / span * (height - 2 * pad):.0f}" for i, p in enumerate(pts))
