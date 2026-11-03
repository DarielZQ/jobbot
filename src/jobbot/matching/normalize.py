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


def normalize_company(name: str) -> str:
    text = normalize_text(name)
    text = _COMPANY_SUFFIXES.sub(" ", text)
    text = re.sub(r"[.-]", " ", text)
    return _SPACES.sub(" ", text).strip()


def normalize_title(title: str) -> str:
    text = normalize_text(title)
    # Drop requisition-like suffixes: "IT Support Analyst - JR0123456", "(Req 1234)"
    text = re.sub(r"\b(jr|req|r)?\d{4,}\b", " ", text)
    text = re.sub(r"[.-]", " ", text)
    return _SPACES.sub(" ", text).strip()
