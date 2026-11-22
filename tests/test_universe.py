import csv
from pathlib import Path

ROWS = list(csv.DictReader((Path(__file__).resolve().parent.parent / "config" / "universe.csv").open()))


def test_universe_has_100_unique_tickers():
    assert len(ROWS) == 100
    assert len({r["ticker"] for r in ROWS}) == 100


def test_ciks_are_zero_padded_to_10_digits():
    assert all(len(r["cik"]) == 10 and r["cik"].isdigit() for r in ROWS)


def test_ranks_are_1_to_100_and_top_20_are_demo():
    assert sorted(int(r["rank"]) for r in ROWS) == list(range(1, 101))
    assert {r["ticker"] for r in ROWS if r["is_demo"] == "true"} == {
        r["ticker"] for r in ROWS if int(r["rank"]) <= 20
    }
