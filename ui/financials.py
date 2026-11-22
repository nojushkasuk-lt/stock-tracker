"""Formatting and the revenue / margin chart for the financials section. Pure functions, no I/O."""

from datetime import date

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from tracker.analysis.metrics import AnnualPoint, Metrics

GREEN = "#0a9f6e"
MUTED = "#94a3b8"
NA = "n/a"


def money(v: float | None) -> str:
    if v is None:
        return NA
    sign, a = ("-" if v < 0 else ""), abs(v)
    for limit, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if a >= limit:
            return f"{sign}${a / limit:,.2f}{suffix}" if a < limit * 10 else f"{sign}${a / limit:,.1f}{suffix}"
    return f"{sign}${a:,.0f}"


def percent(v: float | None, signed: bool = False) -> str:
    if v is None:
        return NA
    return f"{v * 100:+.1f}%" if signed else f"{v * 100:.1f}%"


def multiple(v: float | None) -> str:
    return NA if v is None else f"{v:.2f}×"


def eps(v: float | None) -> str:
    return NA if v is None else f"${v:,.2f}"


def as_of_text(d: date | None) -> str:
    return "No filed figures yet" if d is None else f"Trailing 12 months to {d:%b %Y}, from SEC filings"


def cards(m: Metrics) -> list[dict]:
    """What to show: label, value, optional delta (growth) and a tooltip. Not-available cards say why."""
    ebitda_note = "EBITDA is approximate (depreciation + intangible amortization)." if m.ebitda_basis == "approx" else ""
    return [
        {"label": "Revenue", "value": money(m.revenue_ttm), "delta": percent(m.revenue_growth_yoy, True) if m.revenue_growth_yoy is not None else None,
         "help": m.notes.get("revenue") or m.notes.get("revenue_growth_yoy") or "Trailing 12 months. The change is versus the 12 months a year earlier."},
        {"label": "Operating margin", "value": percent(m.operating_margin),
         "help": m.notes.get("operating_margin") or "Operating income / revenue, as filed (not adjusted for one-off charges)."},
        {"label": "Net margin", "value": percent(m.net_margin), "help": "Net income / revenue."},
        {"label": "EPS (diluted)", "value": eps(m.eps_diluted_ttm), "help": "Diluted earnings per share, trailing 12 months."},
        {"label": "Net debt", "value": money(m.net_debt),
         "help": "Total debt minus cash and short-term investments. A negative number means net cash."},
        {"label": "Net debt / EBITDA", "value": multiple(m.net_debt_to_ebitda),
         "help": m.notes.get("net_debt_to_ebitda") or ("Net debt divided by EBITDA. " + ebitda_note).strip()},
    ]


def revenue_margin_figure(history: list[AnnualPoint]) -> go.Figure | None:
    """Yearly revenue (bars) with margin (line). None if there is nothing to draw."""
    if not history:
        return None
    x = [p.year_end.year if p.year_end.month > 2 else p.year_end.year - 1 for p in history]
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=x, y=[p.revenue / 1e9 for p in history], name="Revenue", marker_color=GREEN, opacity=0.85,
                hovertemplate="%{x}: $%{y:,.1f}B<extra>Revenue</extra>", secondary_y=False)
    pts = [(xi, p) for xi, p in zip(x, history) if p.margin is not None]
    if pts:
        kind = "Operating margin" if all(p.margin_kind == "operating" for _, p in pts) else "Margin"
        fig.add_scatter(x=[xi for xi, _ in pts], y=[p.margin * 100 for _, p in pts], name=kind, mode="lines+markers",
                        line=dict(color=MUTED, width=2), marker=dict(size=7),
                        hovertemplate="%{x}: %{y:.1f}%<extra>" + kind + "</extra>", secondary_y=True)
    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=0), height=300, showlegend=True, bargap=0.35,
        legend=dict(orientation="h", y=-0.12, x=0), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(type="category", showgrid=False), hovermode="x unified",
    )
    fig.update_yaxes(showgrid=False, showticklabels=False, zeroline=False, secondary_y=False)
    fig.update_yaxes(showgrid=False, showticklabels=False, zeroline=False, secondary_y=True, rangemode="tozero")
    return fig
