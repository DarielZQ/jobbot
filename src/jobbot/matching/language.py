"""Posting language (es/en) and which resume to send (ADR-015)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from jobbot import paths
from jobbot.config import SearchRules

_WORDS = re.compile(r"[a-záéíóúñü]+")


def _vocab(*lines: str) -> frozenset[str]:
    return frozenset(" ".join(lines).split())


# Frequent words of job posts; a hit in one list is a vote for that language.
_ES = _vocab(
    "de la el los las del en y para con por una un se que su sus al como o es son",
    "experiencia conocimientos requisitos años soporte técnico tecnico analista auxiliar",
    "servicio ayuda mesa sistemas empresa trabajo puesto funciones nivel inglés ingles",
    "datos tecnología tecnologia redes atención atencion cliente usuarios",
)
_EN = _vocab(
    "the and of to for with in on at an you we our your is are be will as or this that",
    "experience requirements years skills support engineer specialist analyst technician",
    "desk service customer team role responsibilities knowledge level english data",
)


def detect_language(title: str, description: str = "") -> str:
    """'es' or 'en'. The title weighs triple; ties go to English (most multinational posts)."""

    def score(text: str, weight: int) -> tuple[int, int]:
        words = _WORDS.findall(text.lower())
        accents = len(re.findall(r"[áéíóúñ]", text.lower()))
        es = sum(w in _ES for w in words) + accents
        en = sum(w in _EN for w in words)
        return es * weight, en * weight

    es_title, en_title = score(title, 3)
    es_desc, en_desc = score(description[:3000], 1)
    return "es" if es_title + es_desc > en_title + en_desc else "en"


@dataclass(frozen=True)
class ResumeAdvice:
    variant: str  # e.g. "it-support"
    lang: str  # "es" | "en"

    @property
    def filename(self) -> str:
        return f"{self.variant}_{self.lang}.pdf"

    @property
    def path(self) -> Path:
        return paths.resumes_dir() / self.filename

    @property
    def label(self) -> str:
        return f"{self.variant} ({'español' if self.lang == 'es' else 'inglés'})"


def recommend_resume(
    rules: SearchRules, role_family: str, title: str, description: str = ""
) -> ResumeAdvice:
    """CV variant from the role family (config/search.yaml `cv:`), language from the posting.

    A job without a known family gets the CV of the first family that has one.
    """
    family = rules.role_families.get(role_family)
    variant = family.cv if family and family.cv else ""
    if not variant:
        variant = next((f.cv for f in rules.role_families.values() if f.cv), "cv")
    return ResumeAdvice(variant, detect_language(title, description))
