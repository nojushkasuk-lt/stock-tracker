"""One .md file per prompt. load("move_note") returns the text of move_note.md."""

from functools import cache
from pathlib import Path

DIR = Path(__file__).resolve().parent


@cache
def load(name: str) -> str:
    return (DIR / f"{name}.md").read_text().strip()
