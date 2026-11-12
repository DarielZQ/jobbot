"""iCIMS career portals (jobs-<company>.icims.com): public search pages, allowed by robots.txt.

List:   GET https://{host}/jobs/search?ss=1&{search}&in_iframe=1&pr={page}  (job cards)
Detail: GET {job url}?in_iframe=1  ->  schema.org JobPosting (JSON-LD): datePosted, description.
iCIMS has no public API: the portal shows its results inside an iframe, and `in_iframe=1` returns
that inner page. Only jobs that pass the title and location filters get their detail page
(`enrich`). See docs/platforms/icims.md.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from collections.abc import Iterable, Iterator
from datetime import datetime

from jobbot.config import ICimsTarget
from jobbot.core.http import HttpClient
from jobbot.core.models import Job
from jobbot.discovery.base import Source

MAX_PAGES = 10
_CARD = re.compile(r'<li class="iCIMS_JobCardItem">(.*?)</li>', re.S)
_LINK = re.compile(r'href="(https?://[^"?]+/jobs/(\d+)/[^"?/]+/job)[^"]*"')
_TITLE = re.compile(r"<h3[^>]*>(.*?)</h3>", re.S)
_LOCATION = re.compile(r"Job Locations</span>\s*<span[^>]*>(.*?)</span>", re.S)
_JSON_LD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
_TAG = re.compile(r"<[^>]+>")


def _text(fragment: str) -> str:
    return " ".join(html_lib.unescape(_TAG.sub(" ", fragment)).split())


def job_posting(page: str) -> dict:
    """The schema.org JobPosting of a detail page, or {}."""
    for block in _JSON_LD.findall(page):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
    return {}


class ICimsSource(Source):
    def __init__(self, client: HttpClient, target: ICimsTarget) -> None:
        super().__init__(client)
        self.target = target
        self.tenant = target.host.split(".")[0].removeprefix("jobs-")
        self.name = f"icims:{self.tenant}"

    def fetch(self) -> Iterable[Job]:
        # Asking past the last page returns the last one again: stop when nothing is new.
        seen: set[str] = set()
        for page in range(MAX_PAGES):
            fresh = [job for job in self._page(page) if job.ats_job_id not in seen]
            if not fresh:
                return
            seen.update(job.ats_job_id for job in fresh)
            yield from fresh

    def enrich(self, job: Job) -> Job:
        posting = job_posting(self.client.get_text(f"{job.url}?in_iframe=1", accept="text/html"))
        published = posting.get("datePosted")
        return job.model_copy(
            update={
                "description": posting.get("description", ""),
                "posted_at": datetime.fromisoformat(published) if published else None,
            }
        )

    def _page(self, page: int) -> Iterator[Job]:
        query = f"&{self.target.search}" if self.target.search else ""
        url = f"https://{self.target.host}/jobs/search?ss=1{query}&in_iframe=1&pr={page}"
        for card in _CARD.findall(self.client.get_text(url, accept="text/html")):
            link, title = _LINK.search(card), _TITLE.search(card)
            if not (link and title):
                continue
            location = _LOCATION.search(card)
            yield Job(
                source=self.name,
                ats="icims",
                ats_job_id=f"{self.tenant}:{link.group(2)}",
                company=self.target.company,
                title=_text(title.group(1)),
                # "CR-H-Costa Rica | CO-Bogotá": country and region codes, then the place
                location=_text(location.group(1)) if location else "",
                url=link.group(1),
            )
