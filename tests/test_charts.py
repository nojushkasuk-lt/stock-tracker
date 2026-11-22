import json
import re
from datetime import date

import pytest

from tracker.data import charts
from ui.chart import LIB_URL, chart_html


class FakeProvider:
    def __init__(self, points):
        self.points, self.calls = points, 0

    def daily_closes(self, ticker):
        self.calls += 1
        if isinstance(self.points, Exception):
            raise self.points
        return self.points


PTS = [(date(2026, 1, 1), 10.0), (date(2026, 1, 2), 11.0)]


@pytest.fixture(autouse=True)
def _clear_cache():
    charts._cache.clear()


def test_none_provider_turns_charts_off():
    assert charts.get_chart_provider("none") is None
    assert charts.get_chart_series("AAPL", provider=None) is None


def test_prod_default_is_none(monkeypatch):
    import importlib

    from tracker import config

    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.delenv("CHART_PROVIDER", raising=False)
    importlib.reload(config)
    try:
        assert config.CHART_PROVIDER == "none"
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_series_is_cached_in_memory():
    p = FakeProvider(PTS)
    clock = iter([0, 10, 5000]).__next__
    assert charts.get_chart_series("AAPL", p, now=clock).points == PTS
    assert charts.get_chart_series("AAPL", p, now=clock).points == PTS
    assert p.calls == 1  # second call inside the cache window
    charts.get_chart_series("AAPL", p, now=clock)
    assert p.calls == 2  # expired


def test_too_little_data_or_provider_error_gives_none():
    assert charts.get_chart_series("X", FakeProvider(PTS[:1])) is None
    assert charts.get_chart_series("X", FakeProvider(RuntimeError("boom"))) is None


def test_chart_html_keeps_credit_pins_library_and_data_is_valid_json():
    html = chart_html("Apple · AAPL", [("2026-01-01", 10.0), ("2026-01-02", 11.5)])
    assert "https://www.tradingview.com/" in html and "TradingView Lightweight Charts" in html
    assert "lightweight-charts@4.2.0" in LIB_URL  # pinned version, not @latest
    data = json.loads(re.search(r"const DATA = (\[.*?\]);", html, re.S).group(1))
    assert data == [{"time": "2026-01-01", "value": 10.0}, {"time": "2026-01-02", "value": 11.5}]


def test_chart_html_escapes_the_name():
    html = chart_html("<script>alert(1)</script>", [("2026-01-01", 1.0), ("2026-01-02", 2.0)])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_services_returns_iso_dates_and_intraday(monkeypatch):
    from tracker import services

    intra = {"1D": [(1, 1.0), (2, 2.0)]}
    monkeypatch.setattr(services, "get_chart_series", lambda t: charts.ChartSeries(t, PTS, intra))
    d = services.get_chart_data("aapl")
    assert d.daily == [("2026-01-01", 10.0), ("2026-01-02", 11.0)] and d.intraday == intra
    monkeypatch.setattr(services, "get_chart_series", lambda t: None)
    assert services.get_chart_data("aapl") is None


def test_intraday_is_optional_and_failures_do_not_break_the_chart():
    class P(FakeProvider):
        def intraday(self, ticker):
            raise RuntimeError("no intraday")

    assert charts.get_chart_series("A", P(PTS)).intraday == {}

    class Q(FakeProvider):
        def intraday(self, ticker):
            return {"1D": [(1, 1.0), (2, 1.1)], "1W": [(1, 1.0)]}  # 1W has too few points

    assert list(charts.get_chart_series("B", Q(PTS)).intraday) == ["1D"]


def test_chart_html_embeds_intraday_and_drops_unknown_keys():
    html = chart_html("X", [("2026-01-01", 1.0), ("2026-01-02", 2.0)], {"1D": [(100, 1.0), (200, 2.0)], "evil": [(1, 1.0)]})
    intra = json.loads(re.search(r"const INTRA = (\{.*?\});", html, re.S).group(1))
    assert list(intra) == ["1D"] and intra["1D"][0] == {"time": 100, "value": 1.0}
    for label in ("1D", "1W", "1M", "3M", "1Y", "Max"):
        assert f'"{label}"' in html


def test_thin_keeps_recent_days_and_the_last_point_and_shrinks_old_history():
    from ui.chart import thin

    pts = [(date(y, m, 1).isoformat(), 1.0) for y in range(1990, 2027) for m in range(1, 13)]
    # add daily points for the last 5 years
    daily = [(date.fromordinal(date(2021, 12, 1).toordinal() + i).isoformat(), 2.0) for i in range(0, 1800)]
    pts = [p for p in pts if p[0] < "2021-12-01"] + daily
    out = thin(pts)
    assert out[-1] == pts[-1]
    assert len(out) < len(pts)
    last_year = int(pts[-1][0][:4])
    recent_cut = f"{last_year - 5}{pts[-1][0][4:]}"
    assert [p for p in out if p[0] >= recent_cut] == [p for p in pts if p[0] >= recent_cut]
    assert thin([]) == []
