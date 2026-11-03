"""elempleo Costa Rica: public search result pages (HTML), allowed by robots.txt.

GET https://www.elempleo.com/cr/ofertas-empleo/<search slug>
Each result is a `result-item` block with js-offer-title / js-offer-company / js-offer-city /
js-offer-date. Low frequency (min_hours_between_runs). See docs/platforms/job-boards.md.
"""

from __future__ import annotations

import html as html_lib
import re
from collections.abc import Iterable
from datetime import datetime

from jobbot.config import ElempleoTarget
from jobbot.core.http import HttpClient
from jobbot.core.models import Job
from jobbot.discovery.base import Source

BASE = "https://www.elempleo.com"
_OFFER_LINK = re.compile(r"<a\b[^>]*\bjs-offer-title\b[^>]*>", re.I)
_HREF = re.compile(r'href="(/cr/ofertas-trabajo/[^"/]+/(\d+))"', re.I)
_TITLE_ATTR = re.compile(r'title="([^"]*)"', re.I)
_FIELD = r"\b{}\b[^>]*>(.*?)</span>"
_TAG = re.compile(r"<[^>]+>")
_MONTHS = {
    m: i
    for i, m in enumerate(
        ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"], 1
    )
}


def _text(fragment: str) -> str:
    return " ".join(html_lib.unescape(_TAG.sub(" ", fragment)).split())


def _field(block: str, css_class: str) -> str:
    match = re.search(_FIELD.format(re.escape(css_class)), block, re.I | re.S)
    return _text(match.group(1)) if match else ""


def _published(value: str) -> datetime | None:
    """'Publicado 23 Oct 2026' -> datetime(2026, 10, 23)."""
    match = re.search(r"(\d{1,2})\s+([A-Za-z]{3})\w*\s+(\d{4})", value)
    if not match or match.group(2).lower() not in _MONTHS:
        return None
    return datetime(int(match.group(3)), _MONTHS[match.group(2).lower()], int(match.group(1)))


def parse_results(page: str) -> list[Job]:
    jobs: list[Job] = []
    for block in page.split('class="result-item"')[1:]:
        link = _OFFER_LINK.search(block)
        href = _HREF.search(link.group(0)) if link else None
        if not link or not href:
            continue
        title_attr = _TITLE_ATTR.search(link.group(0))
        title = html_lib.unescape(title_attr.group(1)).strip() if title_attr else ""
        city = _field(block, "js-offer-city")
        jobs.append(
            Job(
                source="elempleo",
                ats="elempleo",
                ats_job_id=href.group(2),
                company=_field(block, "js-offer-company") or "(elempleo)",
                title=title,
                location=f"{city}, Costa Rica" if city else "Costa Rica",
                url=f"{BASE}{href.group(1)}",
                posted_at=_published(_field(block, "js-offer-date")),
            )
        )
    return jobs


class ElempleoSource(Source):
    name = "elempleo"

    def __init__(self, client: HttpClient, target: ElempleoTarget) -> None:
        super().__init__(client)
        self.target = target
        self.min_hours_between_runs = target.min_hours_between_runs

    def fetch(self) -> Iterable[Job]:
        seen: set[str] = set()
        for search in self.target.searches:
            page = self.client.get_text(f"{BASE}/cr/ofertas-empleo/{search}", accept="text/html")
            for job in parse_results(page):
                if job.ats_job_id not in seen:
                    seen.add(job.ats_job_id)
                    yield job
