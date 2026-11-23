from datetime import date

from tracker.data import wikidata as w


def b(**kv):
    return {k: {"value": v} for k, v in kv.items()}


def test_pick_logo_skips_white_versions_and_prefers_svg():
    urls = ["http://commons.wikimedia.org/wiki/Special:FilePath/Apple%20logo%20white.svg",
            "http://commons.wikimedia.org/wiki/Special:FilePath/Apple%20logo%20black.png",
            "http://commons.wikimedia.org/wiki/Special:FilePath/Apple%20logo%20black.svg"]
    assert w.pick_logo(urls).endswith("black.svg")
    assert w.pick_logo([]) is None


def test_pick_ceo_takes_the_most_recent_current_one_and_skips_unlabelled():
    assert w.pick_ceo(["Jensen Huang|1993-01-01T00:00:00Z", "Colette Kress|2026-11-12T00:00:00Z"]) == ("Colette Kress", date(2026, 11, 12))
    assert w.pick_ceo(["Q106028933|2026-09-01T00:00:00Z"]) == (None, None)
    assert w.pick_ceo(["Larry Fink|"]) == ("Larry Fink", None)


def test_parse_keeps_the_richer_item_when_two_share_a_cik():
    sep = w.SEP
    rows = [b(key="0000320193", item="http://www.wikidata.org/entity/Q1", logos=""),
            b(key="0000320193", item="http://www.wikidata.org/entity/Q312", hq="Cupertino", founded="1976-04-01T00:00:00Z",
              staff="164000", ceos=f"John Ternus|2026-09-01T00:00:00Z{sep}|", wiki="https://en.wikipedia.org/wiki/Apple_Inc.",
              logos="http://commons.wikimedia.org/wiki/Special:FilePath/Apple%20logo%20black.svg")]
    f = w.parse(rows)["0000320193"]
    assert (f.qid, f.ceo, f.ceo_since, f.founded, f.employees) == ("Q312", "John Ternus", date(2026, 9, 1), 1976, 164000)


def test_logo_thumb_asks_commons_for_a_png_of_the_width():
    assert w.logo_thumb("http://commons.wikimedia.org/wiki/Special:FilePath/Apple%20logo%20black.svg", 96) == \
        "https://commons.wikimedia.org/wiki/Special:FilePath/Apple%20logo%20black.svg?width=96"


def test_ticker_fallback_uses_the_dot_form_on_us_exchanges():
    q = w.by_ticker(["BRK-B"])
    assert '"BRK.B"' in q and "wd:Q13677" in q
