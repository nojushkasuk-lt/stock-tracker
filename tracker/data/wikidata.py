"""Company key facts and logos from Wikidata (CC0), matched by SEC CIK (property P5531).

Logos are Wikimedia Commons files; each file's own licence applies (most are public-domain text logos),
so pages credit "Logos: Wikimedia Commons". Facts can lag reality, so every fact is shown with its source.
"""

import hashlib
import re
import time
from dataclasses import dataclass
from datetime import date
from urllib.parse import quote, unquote

import httpx

SPARQL = "https://query.wikidata.org/sparql"
USER_AGENT = "StockTracker/0.1 (personal portfolio project; https://github.com)"
BATCH = 40
SEP = "␟"  # unit separator for GROUP_CONCAT

QUERY = """
SELECT ?key ?item
  (SAMPLE(?article) AS ?wiki)
  (GROUP_CONCAT(DISTINCT STR(?logo); separator="{sep}") AS ?logos)
  (GROUP_CONCAT(DISTINCT CONCAT(COALESCE(?ceoEn, ?ceoAny, ""), "|", COALESCE(STR(?ceoStart), "")); separator="{sep}") AS ?ceos)
  (SAMPLE(COALESCE(?hqEn, "")) AS ?hq) (SAMPLE(?countryEn) AS ?country)
  (MIN(?inception) AS ?founded) (MAX(?employees) AS ?staff) (SAMPLE(?site) AS ?website)
WHERE {{
  {match}
  OPTIONAL {{ ?item wdt:P154 ?logo }}
  OPTIONAL {{ ?item p:P169 ?st . ?st ps:P169 ?ceo . ?st wikibase:rank ?rank . FILTER(?rank != wikibase:DeprecatedRank)
             FILTER NOT EXISTS {{ ?st pq:P582 [] }}
             OPTIONAL {{ ?st pq:P580 ?ceoStart }}
             OPTIONAL {{ ?ceo rdfs:label ?ceoEn FILTER(LANG(?ceoEn) = "en") }}
             OPTIONAL {{ ?ceo rdfs:label ?ceoAny FILTER(LANG(?ceoAny) IN ("mul", "de", "fr", "es")) }} }}
  OPTIONAL {{ ?item wdt:P159 ?hqi . ?hqi rdfs:label ?hqEn FILTER(LANG(?hqEn) = "en") }}
  OPTIONAL {{ ?item wdt:P17 ?c . ?c rdfs:label ?countryEn FILTER(LANG(?countryEn) = "en") }}
  OPTIONAL {{ ?item wdt:P571 ?inception }}
  OPTIONAL {{ ?item wdt:P1128 ?employees }}
  OPTIONAL {{ ?item wdt:P856 ?site }}
  OPTIONAL {{ ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> }}
}}
GROUP BY ?key ?item
"""


@dataclass(frozen=True)
class Facts:
    cik: str
    qid: str
    logo_url: str | None
    ceo: str | None
    ceo_since: date | None
    headquarters: str | None
    country: str | None
    founded: int | None
    employees: int | None
    website: str | None
    wikipedia_url: str | None


_BAD_LOGO = re.compile(r"white|inverse|inverted|negative|dark[ _-]?(mode|bg|background)|reverse", re.I)
_GOOD_LOGO = re.compile(r"\b(logo|logotype|wordmark)\b", re.I)


def pick_logo(urls: list[str]) -> str | None:
    """Prefer a logo that reads on a light tile: skip white / inverted versions, prefer SVG."""
    if not urls:
        return None
    def score(u: str) -> tuple:
        name = unquote(u.rsplit("/", 1)[-1])
        return (bool(_BAD_LOGO.search(name)), not name.lower().endswith(".svg"), not _GOOD_LOGO.search(name), len(name))
    return sorted(urls, key=score)[0]


def commons_logo(filename: str) -> tuple[str, str]:
    """Direct Commons image URL and its attribution and license page."""
    title = filename.replace(" ", "_")
    digest = hashlib.md5(title.encode(), usedforsecurity=False).hexdigest()
    path = quote(title, safe="")
    return (f"https://upload.wikimedia.org/wikipedia/commons/{digest[0]}/{digest[:2]}/{path}",
            f"https://commons.wikimedia.org/wiki/File:{path}")


def logo_thumb(url: str, width: int = 128) -> str:
    """Commons Special:FilePath URL -> a PNG thumbnail of the given width (SVGs are rasterised by Commons)."""
    name = unquote(url.rsplit("/", 1)[-1])
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(name)}?width={width}"


def _date(s: str | None) -> date | None:
    m = re.match(r"(-?\d{4})-(\d{2})-(\d{2})", s or "")
    if not m or m.group(1).startswith("-"):
        return None
    try:
        return date(int(m.group(1)), max(1, int(m.group(2))), max(1, int(m.group(3))))
    except ValueError:
        return None


def pick_ceo(entries: list[str]) -> tuple[str | None, date | None]:
    """'Name|start' entries without an end date: the one who started most recently."""
    people = []
    for e in entries:
        name, _, start = e.partition("|")
        if name and not re.fullmatch(r"Q\d+", name):
            people.append((_date(start) or date.min, name))
    if not people:
        return None, None
    start, name = max(people)
    return name, (None if start == date.min else start)


def parse(bindings: list[dict]) -> dict[str, Facts]:
    out: dict[str, Facts] = {}
    for b in bindings:
        v = {k: x["value"] for k, x in b.items()}
        cik = v["key"]
        split = lambda k: [s for s in v.get(k, "").split(SEP) if s]  # noqa: E731
        ceo, since = pick_ceo(split("ceos"))
        founded = _date(v.get("founded"))
        staff = v.get("staff")
        facts = Facts(
            cik=cik, qid=v["item"].rsplit("/", 1)[-1], logo_url=pick_logo(split("logos")), ceo=ceo, ceo_since=since,
            headquarters=v.get("hq") or None, country=v.get("country"), founded=founded.year if founded else None,
            employees=int(float(staff)) if staff else None, website=v.get("website"), wikipedia_url=v.get("wiki"))
        prev = out.get(cik)
        # Several items can share a CIK (e.g. a parent and its old name): keep the one with more facts.
        if prev is None or _richness(facts) > _richness(prev):
            out[cik] = facts
    return out


def _richness(f: Facts) -> int:
    return sum(x is not None for x in (f.logo_url, f.ceo, f.headquarters, f.founded, f.employees, f.wikipedia_url))


US_EXCHANGES = "wd:Q13677 wd:Q82059 wd:Q1200591"  # NYSE, Nasdaq, Nasdaq Stock Market


def by_cik(ciks: list[str]) -> str:
    return "VALUES ?key { " + " ".join(f'"{c}"' for c in ciks) + " } ?item wdt:P5531 ?key ."


def by_ticker(tickers: list[str]) -> str:
    """Fallback for companies whose Wikidata item has no CIK: ticker on a US exchange (P414 + qualifier P249)."""
    vals = " ".join(f'"{t.replace("-", ".")}"' for t in tickers)
    return (f"VALUES ?key {{ {vals} }} VALUES ?ex {{ {US_EXCHANGES} }} "
            "?item p:P414 ?lst . ?lst ps:P414 ?ex ; pq:P249 ?key . FILTER NOT EXISTS { ?lst pq:P582 [] }")


def _client() -> httpx.Client:
    return httpx.Client(timeout=90, headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"})


def _run(keys: list[str], match, client: httpx.Client, pause: float) -> dict[str, Facts]:
    out: dict[str, Facts] = {}
    for i in range(0, len(keys), BATCH):
        q = QUERY.format(sep=SEP, match=match(keys[i:i + BATCH]))
        r = client.get(SPARQL, params={"query": q, "format": "json"})
        r.raise_for_status()
        out.update(parse(r.json()["results"]["bindings"]))
        if i + BATCH < len(keys):
            time.sleep(pause)
    return out


def fetch(ciks: list[str], client: httpx.Client | None = None, pause: float = 1.0) -> dict[str, Facts]:
    """Facts for 10-digit CIKs. Missing companies are simply absent from the result."""
    return _run(ciks, by_cik, client or _client(), pause)


def fetch_by_ticker(tickers: list[str], client: httpx.Client | None = None, pause: float = 1.0) -> dict[str, Facts]:
    """{ticker (dot form, e.g. BRK.B): Facts}."""
    return _run(tickers, by_ticker, client or _client(), pause)
