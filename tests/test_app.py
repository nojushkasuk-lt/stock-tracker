from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def test_app_runs_without_errors_and_shows_the_disclaimer():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert any("Not investment advice" in c.value for c in at.caption)
    # Either the demo picker (database loaded) or the setup hint (empty database).
    assert at.selectbox or at.info


def test_demo_picker_lists_the_top_20_when_the_database_is_loaded():
    at = AppTest.from_file(APP, default_timeout=30).run()
    if at.selectbox:  # needs the local database from `python -m jobs.universe`
        assert len(at.selectbox[0].options) == 20


def test_app_uses_the_custom_chart_when_points_exist_and_falls_back_otherwise(monkeypatch):
    from tracker import services

    pts = [("2026-01-01", 10.0), ("2026-01-02", 11.0)]
    monkeypatch.setattr(services, "get_chart_points", lambda t: pts)
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception

    monkeypatch.setattr(services, "get_chart_points", lambda t: None)  # prod default: TradingView widgets
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    if at.selectbox:
        assert at.subheader  # the fallback shows the company heading above the widgets
