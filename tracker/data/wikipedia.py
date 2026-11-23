"""Plain-text Wikipedia article sections for the profile's About paragraph (history only).

Wikipedia text is CC BY-SA: we never reproduce it. The model summarises it in its own words and the page links
the article as a source. Only the lead and the History section are sent, capped.
"""

import re
from urllib.parse import unquote

import httpx

API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "StockTracker/0.1 (personal portfolio project)"
MAX_CHARS = 12_000
_HEADING = re.compile(r"^(=+)\s*(.+?)\s*\1\s*$", re.M)


def title_from_url(url: str) -> str:
    return unquote(url.rstrip("/").rsplit("/wiki/", 1)[-1]).replace("_", " ")


def lead_and_history(text: str, max_chars: int = MAX_CHARS) -> str:
    """The article's lead (before the first heading) plus its History section, if any."""
    heads = list(_HEADING.finditer(text))
    lead = text[: heads[0].start()] if heads else text
    hist = ""
    for i, h in enumerate(heads):
        if len(h.group(1)) == 2 and "history" in h.group(2).lower():
            end = next((x.start() for x in heads[i + 1:] if len(x.group(1)) <= 2), len(text))
            hist = text[h.end():end]
            break
    out = lead.strip()
    if hist:
        out += "\n\nHistory:\n" + _condense(hist, max(2000, max_chars - len(out) - 20))
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out if len(out) <= max_chars else out[:max_chars].rsplit(" ", 1)[0] + " [...]"


def _condense(hist: str, budget: int) -> str:
    """Keep the start of every subsection so the whole arc fits (founding to today), not just the early years."""
    parts = re.split(r"^=+\s*(.+?)\s*=+\s*$", hist, flags=re.M)
    chunks = [("", parts[0])] + list(zip(parts[1::2], parts[2::2]))
    chunks = [(h, b.strip()) for h, b in chunks if b.strip()]
    if not chunks:
        return ""
    each = max(300, budget // len(chunks))
    out = []
    for h, body in chunks:
        piece = body if len(body) <= each else body[:each].rsplit(" ", 1)[0] + " [...]"
        out.append((f"{h}: " if h else "") + piece)
    return "\n".join(out)


def fetch(url: str, client: httpx.Client | None = None) -> str | None:
    client = client or httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT})
    r = client.get(API, params={"action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1,
                                "titles": title_from_url(url), "format": "json", "formatversion": 2})
    r.raise_for_status()
    pages = r.json().get("query", {}).get("pages", [])
    text = pages[0].get("extract") if pages else None
    return lead_and_history(text) if text else None
