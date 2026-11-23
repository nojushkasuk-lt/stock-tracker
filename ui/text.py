"""Safe Markdown for text we did not write by hand (model output, filing labels)."""

import re

_MD = re.compile(r"([\\`*_{}\[\]()#+!|>~$<])")


def md(text: str) -> str:
    """Escape Markdown and LaTeX ($) characters so model text shows exactly as written."""
    return _MD.sub(r"\\\1", text)
