"""Move-note and market services: newest note wins, outlet filter, headline label, alert-day market note."""

from datetime import date, datetime

from test_profile_ui import use_db
from tracker import services
from tracker.models import AiOutput, MarketDay, Move, Universe, User, UserOutlet

D = date(2026, 11, 20)


def note(kind, key, created, claims, sources, ranked, extra=None):
    content = {"summary": "Coverage around the move points to X.", "claims": claims, "confidence": "medium",
               "ranked_source_ids": ranked, "dropped": [], "date": D.isoformat(), "return_pct": -6.0,
               "market_return_pct": -0.3, **(extra or {})}
    return AiOutput(kind=kind, scope_key=key, model="claude-haiku-5-5", input_hash=f"{kind}{created}",
                    content=content, sources=sources, confidence="medium", created_at=created)


SRC = [{"id": "N1", "url": "https://www.reuters.com/a", "outlet": "Reuters"},
       {"id": "N2", "url": "https://www.cnbc.com/b", "outlet": "CNBC"},
       {"id": "F1", "url": "https://www.sec.gov/x.htm", "outlet": "SEC EDGAR"}]


def base_rows():
    return [Universe(ticker="UNH", cik="1", name="UnitedHealth", industry="Health", updated_at=datetime(2026, 1, 1)),
            User(email="a@example.com", created_at=datetime(2026, 1, 1)),
            UserOutlet(email="a@example.com", domain="cnbc.com")]


def test_move_note_view_filters_links_to_the_users_outlets(tmp_path, monkeypatch):
    n = note("stock_note", "UNH", datetime(2026, 11, 20, 22),
             [{"text": "Reports suggest a rule weighed on shares.", "source_ids": ["N1", "N2"]}], SRC[:2], ["N1", "N2"])
    n.id = 1
    use_db(tmp_path, monkeypatch, base_rows() + [n, Move(ticker="UNH", date=D, return_pct=-6.0, scope="stock", note_id=1, status="explained")])
    demo = services.get_move_note("unh")
    assert [l.label for l in demo.links] == ["Reuters", "CNBC"] and demo.headline_based
    mine = services.get_move_note("UNH", "a@example.com")
    assert [l.label for l in mine.links] == ["CNBC"] and [l.label for l in mine.points[0].sources] == ["CNBC"]
    assert mine.scope_label == "Company news" and mine.return_pct == -6.0


def test_shared_market_note_shows_the_stocks_own_move(tmp_path, monkeypatch):
    market = note("market_note", "market", datetime(2026, 11, 20, 22), [], SRC[:1], ["N1"], {"return_pct": -3.6})
    market.id = 1
    move = Move(ticker="UNH", date=D, return_pct=-4.1, scope="market", note_id=1, status="explained")
    use_db(tmp_path, monkeypatch, base_rows() + [market, move])
    v = services.get_move_note("UNH")
    assert (v.scope_label, v.return_pct) == ("Moved with the market", -4.1)


def test_a_newer_refresh_replaces_the_shared_note(tmp_path, monkeypatch):
    market = note("market_note", "market", datetime(2026, 11, 20, 22), [], SRC[:1], ["N1"], {"return_pct": -3.6})
    market.id = 1
    refresh = note("stock_note", "UNH", datetime(2026, 11, 21, 9),
                   [{"text": "The release reported revenue of $10.0 billion.", "source_ids": ["F1"]}], SRC, ["F1"])
    move = Move(ticker="UNH", date=D, return_pct=-4.1, scope="market", note_id=1, status="explained")
    use_db(tmp_path, monkeypatch, base_rows() + [market, move, refresh])
    v = services.get_move_note("UNH")
    assert v.scope == "stock" and not v.headline_based  # cites the SEC filing


def test_market_status_shows_the_note_only_on_alert_days(tmp_path, monkeypatch):
    m = note("market_note", "market", datetime(2026, 11, 20, 22), [], SRC[:1], ["N1"], {"return_pct": -3.6})
    use_db(tmp_path, monkeypatch, [MarketDay(date=D, index_return_pct=-3.6, level="major"), m])
    ms = services.get_market_status()
    assert (ms.level, ms.note.return_pct) == ("major", -3.6)


def test_calm_day_has_no_market_note(tmp_path, monkeypatch):
    use_db(tmp_path, monkeypatch, [MarketDay(date=D, index_return_pct=-0.4, level="none")])
    ms = services.get_market_status()
    assert ms.level == "none" and ms.note is None
