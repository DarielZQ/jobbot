"""Text normalization shared by rules and dedupe."""

from __future__ import annotations

import html
import re
import unicodedata

_COMPANY_SUFFIXES = re.compile(
    r"\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|company|gmbh|plc|"
    r"s\.?\s?a\.?|s\.?\s?r\.?\s?l\.?|sociedad anonima)\b\.?"
)
_TAGS = re.compile(r"<[^>]+>")
_NON_WORD = re.compile(r"[^\w\s+#.-]")
_SPACES = re.compile(r"\s+")


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalize_text(text: str) -> str:
    """Lowercase, no accents, no HTML, single spaces. Keeps + # . - (e.g. 'c#', '3+')."""
    text = html.unescape(html.unescape(text or ""))
    text = _TAGS.sub(" ", text)
    text = strip_accents(text).lower()
    text = _NON_WORD.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


# Words a site may add to or drop from a company name: "Veeam Software" on Indeed is "Veeam" on its
# own career site. Dropped only at the end, and never the first word.
_GENERIC_TAIL = frozenset(
    {
        "software",
        "technologies",
        "technology",
        "solutions",
        "services",
        "systems",
        "group",
        "holdings",
        "international",
        "global",
    }
)


def normalize_company(name: str) -> str:
    text = normalize_text(name)
    text = _COMPANY_SUFFIXES.sub(" ", text)
    words = re.sub(r"[.-]", " ", text).split()
    while len(words) > 1 and words[-1] in _GENERIC_TAIL:
        words.pop()
    return " ".join(words)


def normalize_title(title: str) -> str:
    text = normalize_text(title)
    # Drop requisition-like suffixes: "IT Support Analyst - JR0123456", "(Req 1234)"
    text = re.sub(r"\b(jr|req|r)?\d{4,}\b", " ", text)
    text = re.sub(r"[.-]", " ", text)
    return _SPACES.sub(" ", text).strip()
