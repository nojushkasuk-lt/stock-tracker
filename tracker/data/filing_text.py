"""Readable sections of an EDGAR filing for the profile prompt (rule 5: send sections, not whole filings).

10-K: Item 1 Business, Item 1A Risk Factors, Item 7 MD&A. 10-Q: Part I Item 2 MD&A. 8-K item 2.02: the earnings
release exhibit (EX-99.x). Each section is capped in characters; a cut is marked in the text, never silent.
Filing text goes to the model only and is never stored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

from tracker.data.edgar import EdgarClient

BLOCK_TAGS = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section"}
SKIP_TAGS = {"script", "style", "head", "title"}
HIDDEN = re.compile(r"display\s*:\s*none", re.I)  # inline XBRL keeps its header data in a hidden div

# Characters per section (about 4 characters per token): keeps a 10-K prompt near 45k tokens.
CAPS = {"business": 30_000, "risk_factors": 30_000, "mdna": 100_000, "earnings_release": 60_000}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0
        self._stack: list[bool] = []

    def handle_starttag(self, tag, attrs):
        hidden = tag in SKIP_TAGS or any(k == "style" and v and HIDDEN.search(v) for k, v in attrs)
        if tag not in {"br", "img", "hr", "meta", "link", "input"}:
            self._stack.append(hidden)
            if hidden:
                self._skip += 1
        if tag in BLOCK_TAGS:
            self.parts.append("\n")
        elif tag in {"td", "th"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"br", "img", "hr", "meta", "link", "input"}:
            return
        if self._stack and self._stack.pop():
            self._skip -= 1
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    p = _Text()
    p.feed(html)
    text = "".join(p.parts).replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _heading(item: str) -> re.Pattern:
    # "Item 7." / "ITEM 7 -" / "Item 7:" at the start of a line; "Item 1" must not match "Item 1A" or "Item 10".
    return re.compile(rf"^\s*item\s*{re.escape(item)}(?![0-9a-z])\s*[.:\-—–]?", re.I | re.M)


def section(text: str, start_item: str, end_items: list[str], min_len: int = 2_000) -> str | None:
    """Text from the heading of start_item to the next end_item heading. The table of contents also lists
    the headings, so the longest candidate is taken (the real section, not the contents line)."""
    best = None
    ends = [_heading(e) for e in end_items]
    for m in _heading(start_item).finditer(text):
        stops = [e.search(text, m.end()) for e in ends]
        stop = min((s.start() for s in stops if s), default=len(text))
        body = text[m.start():stop].strip()
        if len(body) >= min_len and (best is None or len(body) > len(best)):
            best = body
    return best


def cap(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text.rfind("\n", 0, limit)
    cut = cut if cut > limit * 0.8 else limit
    return text[:cut] + f"\n[... section cut here: first {cut:,} of {len(text):,} characters]"


@dataclass
class Section:
    key: str      # business, risk_factors, mdna, earnings_release
    label: str    # e.g. "10-K Item 7 MD&A"
    text: str
    url: str


def periodic_sections(text: str, form: str, url: str) -> list[Section]:
    if form == "10-K":
        specs = [("business", "10-K Item 1 Business", "1", ["1A", "1B", "1C", "2"]),
                 ("risk_factors", "10-K Item 1A Risk Factors", "1A", ["1B", "1C", "2"]),
                 ("mdna", "10-K Item 7 MD&A", "7", ["7A", "8"])]
    elif form == "10-Q":
        specs = [("mdna", "10-Q Item 2 MD&A", "2", ["3", "4"])]
    else:
        raise ValueError(f"not a periodic form: {form}")
    out = []
    for key, label, start, ends in specs:
        body = section(text, start, ends)
        if body:
            out.append(Section(key, label, cap(body, CAPS[key]), url))
    return out


EXHIBIT_99 = re.compile(r"ex(hibit)?[-_]?99", re.I)


class FilingFetcher:
    """Downloads filing documents through the EDGAR client (same User-Agent and rate limit)."""

    def __init__(self, edgar: EdgarClient):
        self.edgar = edgar

    def text(self, url: str) -> str:
        return html_to_text(self.edgar.get_text(url))

    def earnings_release_url(self, filing_url: str) -> str | None:
        base = filing_url.rsplit("/", 1)[0]
        items = self.edgar.get_json(f"{base}/index.json")["directory"]["item"]
        names = sorted(i["name"] for i in items if EXHIBIT_99.search(i["name"]) and i["name"].endswith((".htm", ".html")))
        return f"{base}/{names[0]}" if names else None

    def sections(self, form: str, items: str | None, url: str) -> list[Section]:
        if form in ("10-K", "10-Q"):
            return periodic_sections(self.text(url), form, url)
        if form == "8-K" and "2.02" in (items or ""):
            ex = self.earnings_release_url(url)
            if ex:
                return [Section("earnings_release", "8-K item 2.02 earnings release",
                                cap(self.text(ex), CAPS["earnings_release"]), ex)]
        return []
