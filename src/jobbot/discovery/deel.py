"""Deel's own careers page (www.deel.com/careers), allowed by robots.txt (ADR-021).

Deel's Ashby board is empty: the page itself carries every listed job (title, team, countries)
in its Next.js payload, `self.__next_f.push([1, "<chunk>"])`. Each chunk is a JSON string
literal; joined, they hold one `"attributes": {...}` object per job. One request per run, at
most every `min_hours_between_runs`. See docs/platforms/deel.md.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from jobbot.config import DeelTarget
from jobbot.core.http import HttpClient
from jobbot.core.models import Job
from jobbot.discovery.base import Source

BASE = "https://www.deel.com"
_PUSH = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
_JOB = re.compile(r'"attributes":\s*(?=\{\s*"ashby_id")')


def page_jobs(page: str) -> list[dict[str, Any]]:
    """The job objects inside the page, in order, once each."""
    payload = "".join(json.loads(chunk) for chunk in _PUSH.findall(page))
    decoder = json.JSONDecoder()
    jobs: dict[str, dict[str, Any]] = {}
    for match in _JOB.finditer(payload):
        try:
            job, _ = decoder.raw_decode(payload, match.end())
        except json.JSONDecodeError:
            continue
        jobs.setdefault(job["ashby_id"], job)
    return list(jobs.values())


class DeelSource(Source):
    def __init__(self, client: HttpClient, target: DeelTarget) -> None:
        super().__init__(client)
        self.target = target
        self.name = "deel"
        self.min_hours_between_runs = target.min_hours_between_runs

    def fetch(self) -> Iterable[Job]:
        jobs = page_jobs(self.client.get_text(self.target.url, accept="text/html"))
        if not jobs:  # reported as an error: the page changed, not "no openings today"
            raise ValueError("la página de empleos de Deel ya no trae las vacantes (cambió)")
        for job in jobs:
            if job.get("is_listed") is False:
                continue
            countries = job.get("all_locations") or [job.get("location_name") or ""]
            published = job.get("ashby_published_date")
            yield Job(
                source=self.name,
                ats="deel",
                ats_job_id=job["ashby_id"],
                company="Deel",
                title=(job.get("title") or "").strip(),
                # The countries it can be done from; the location filters keep yours
                location=", ".join(c for c in countries if c),
                url=f"{BASE}{job['slug']}" if job.get("slug") else job.get("external_link", ""),
                remote=True,  # Deel is fully remote
                posted_at=datetime.fromisoformat(published) if published else None,
            )
