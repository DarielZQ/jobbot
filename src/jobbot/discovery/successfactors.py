"""SAP SuccessFactors Career Site Builder: the public search page (no login).

List:   GET {base_url}/search/?q=&locationsearch=<país>&locale=en_US&startrow=<n>  (25 per page)
Detail: GET {job url}  ->  schema.org microdata: datePosted and the description.
These sites' robots.txt disallows /services/ (the RSS feed, and the JSON API that newer pages load
with JavaScript) and allows /search/ and /job/ (ADR-028). Only jobs that pass the title and
location filters get their detail page (`enrich`). See docs/platforms/successfactors.md.
"""

from __future__ import annotations

import html as html_lib
import re
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from urllib.parse import quote, urlsplit

from jobbot.config import SuccessFactorsTarget
from jobbot.core.http import HttpClient
from jobbot.core.models import Job
from jobbot.discovery.base import Source, require
from jobbot.matching.normalize import normalize_text

MAX_PAGES = 10
_ROW = re.compile(r'<tr class="data-row">(.*?)</tr>', re.S)
# Each row repeats the link for phones; the first one is enough.
_LINK = re.compile(r'<a\b[^>]*\bhref="(/job/[^"]*?/(\d+)/?)"[^>]*>(.*?)</a>', re.S)
_LOCATION = re.compile(r'<span class="jobLocation">(.*?)</span>', re.S)
_DATE = re.compile(r'<span class="jobDate[^"]*">(.*?)</span>', re.S)
# "Results <b>1 – 25</b> of <b>323</b>"
_TOTAL = re.compile(r'class="paginationLabel".*?of\s*<b>\s*([\d,.]+)\s*</b>', re.S)
_NO_RESULTS = 'id="noresults"'
_DATE_POSTED = re.compile(r'<meta itemprop="datePosted" content="([^"]+)"')
# `<span class="jobdescription">`, or with itemprop="description" on the same span
_DESCRIPTION = re.compile(r'<span\b[^>]*\bclass="jobdescription"[^>]*>')
_SPAN_TAG = re.compile(r"<(/?)span\b", re.I)
_TAG = re.compile(r"<[^>]+>")
_MONTHS = {
    month: number
    for number, month in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}
# "Nov 4, 2026" in the list; "Wed Nov 04 08:00:00 UTC 2026" in the detail page
_LIST_DATE = re.compile(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),\s*(\d{4})")
_DETAIL_DATE = re.compile(r"([A-Za-z]{3}) (\d{1,2}) \d{2}:\d{2}:\d{2} \w+ (\d{4})")


def _text(fragment: str) -> str:
    return " ".join(html_lib.unescape(_TAG.sub(" ", fragment)).split())


def parse_date(text: str) -> datetime | None:
    """The day a job was posted, from the list ("Nov 4, 2026") or the detail page."""
    if match := _LIST_DATE.search(text) or _DETAIL_DATE.search(text):
        month, day, year = match.groups()
        if number := _MONTHS.get(month.lower()):
            return datetime(int(year), number, int(day), tzinfo=UTC)
    return None


def job_description(page: str) -> str:
    """The HTML inside `<span class="jobdescription">`, which nests spans of its own."""
    if not (start := _DESCRIPTION.search(page)):
        return ""
    body = start.end()
    depth = 1
    for tag in _SPAN_TAG.finditer(page, body):
        depth += -1 if tag.group(1) else 1
        if depth == 0:
            return page[body : tag.start()].strip()
    return page[body:].strip()


class SuccessFactorsSource(Source):
    def __init__(self, client: HttpClient, target: SuccessFactorsTarget) -> None:
        super().__init__(client)
        self.target = target
        self.base = target.base_url.rstrip("/")
        self.host = urlsplit(self.base).netloc
        self.name = f"successfactors:{self.host.split('.')[-2] if '.' in self.host else self.host}"

    def fetch(self) -> Iterable[Job]:
        require(self.target.keywords, "el país a buscar (region.country)")
        seen: set[str] = set()
        for _ in range(MAX_PAGES):
            page = self.client.get_text(self._search_url(len(seen)), accept="text/html")
            if _NO_RESULTS in page:
                self.listing_complete = True
                return
            total = _TOTAL.search(page)
            if not total:
                raise ValueError(
                    "la página de búsqueda no trae la lista de vacantes: este sitio la carga con "
                    "JavaScript desde /services/, que su robots.txt prohíbe (ADR-028)"
                )
            fresh = [job for job in self._rows(page) if job.ats_job_id not in seen]
            if not fresh:
                return
            seen.update(job.ats_job_id for job in fresh)
            yield from fresh
            if len(seen) >= int(re.sub(r"\D", "", total.group(1))):
                self.listing_complete = True
                return

    def enrich(self, job: Job) -> Job:
        page = self.client.get_text(job.url, accept="text/html")
        posted = _DATE_POSTED.search(page)
        return job.model_copy(
            update={
                "description": job_description(page),
                "posted_at": (parse_date(posted.group(1)) if posted else None) or job.posted_at,
            }
        )

    def _search_url(self, start: int) -> str:
        url = (
            f"{self.base}/search/?q=&locationsearch={quote(self.target.keywords)}"
            f"&locale={self.target.locale}"
        )
        return f"{url}&startrow={start}" if start else url

    def _rows(self, page: str) -> Iterator[Job]:
        for row in _ROW.findall(page):
            if not (link := _LINK.search(row)):
                continue
            path, job_id, title = link.groups()
            title = _text(title)
            location = _LOCATION.search(row)
            location_text = _text(location.group(1)) if location else ""
            posted = _DATE.search(row)
            yield Job(
                source=self.name,
                ats="successfactors",
                ats_job_id=f"{self.host}:{job_id}",
                company=self.target.company,
                title=title,
                location=location_text,
                url=f"{self.base}{html_lib.unescape(path)}",
                remote="remote" in normalize_text(f"{title} {location_text}"),
                posted_at=parse_date(_text(posted.group(1))) if posted else None,
            )
