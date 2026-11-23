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
    monkeypatch.setattr(services, "get_chart_data", lambda t: services.ChartData(pts, {}))
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception

    monkeypatch.setattr(services, "get_chart_data", lambda t: None)  # prod default: TradingView widgets
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    if at.selectbox:
        assert at.subheader  # the fallback shows the company heading above the widgets


def test_tabs_render_and_coverage_is_off_without_sign_in(monkeypatch):
    from tracker import services

    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    labels = [t.label for t in at.tabs]
    assert {"Stocks", "Market"} <= set(labels) and "Settings" not in labels
    if at.selectbox:  # database loaded: the stock has its own sub-tabs
        assert {"Profile", "Financials", "Coverage", "Filings"} <= set(labels)
    buttons = {b.label for b in at.button}
    assert not buttons & {"Find coverage", "Refresh now", "Save"}  # demo mode: read-only (rule 7)
    assert any("Brave Search API" in c.value for c in at.caption)  # rule 12 credit line


def test_coverage_service_refuses_in_demo_mode(monkeypatch):
    from tracker import services

    cov = services.get_coverage("AAPL")
    assert cov.links == [] and "signed-in" in cov.message


def test_signed_in_user_without_stocks_is_sent_to_settings(monkeypatch):
    from tracker import services

    monkeypatch.setattr(services, "sign_in", lambda email: None)
    monkeypatch.setattr(services, "get_watchlist", lambda email: [])
    monkeypatch.setattr(services, "get_outlet_choice", lambda email: set())
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["dev_email"] = "a@example.com"
    at.run()
    assert not at.exception
    assert "Settings" in [t.label for t in at.tabs]
    assert any("Pick up to 15" in i.value for i in at.info)
    assert "Save" in {b.label for b in at.button}


def test_dev_sign_in_is_never_offered_in_prod(monkeypatch):
    from tracker import config, services

    monkeypatch.setattr(config, "APP_ENV", "prod")
    assert services.dev_sign_in_allowed() is False
