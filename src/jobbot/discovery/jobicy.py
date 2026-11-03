"""Jobicy: public remote-jobs API (no auth).

GET https://jobicy.com/api/jobs?count=200&geo=costa-rica (&cursor=... for the next page)
The feed covers the last 7 days. Fair use: keep the Jobicy URL as the source and do not start a
new polling pass more often than once an hour (`min_hours_between_runs`).
See docs/platforms/job-boards.md.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any
from urllib.parse import quote

from jobbot.config import JobicyTarget
from jobbot.core.http import HttpClient
from jobbot.core.models import Job
from jobbot.discovery.base import Source, require

API = "https://jobicy.com/api/jobs"
PAGE_SIZE = 200
MAX_PAGES = 5
_ENTRY_LEVELS = ("any", "entry", "junior", "midweight", "mid")


class JobicySource(Source):
    name = "jobicy"

    def __init__(self, client: HttpClient, target: JobicyTarget) -> None:
        super().__init__(client)
        self.target = target
        self.min_hours_between_runs = target.min_hours_between_runs

    def fetch(self) -> Iterable[Job]:
        require(self.target.geo, "el país como lo escribe Jobicy (region.country_slug)")
        seen: set[str] = set()
        cursor = None
        for _ in range(MAX_PAGES):
            url = f"{API}?count={PAGE_SIZE}&geo={quote(self.target.geo)}"
            if cursor:
                url += f"&cursor={quote(cursor)}"
            data = self.client.get_json(url)
            for posting in data.get("jobs") or []:
                if str(posting["id"]) not in seen:
                    seen.add(str(posting["id"]))
                    yield _to_job(posting)
            cursor = data.get("nextCursor")
            if not cursor:
                break


def _seniority(level: str) -> str:
    """'Senior' only when no entry-friendly level is listed ("Entry-Level, Junior", "Any")."""
    lowered = level.lower()
    if lowered and not any(word in lowered for word in _ENTRY_LEVELS):
        return "Senior"
    return level or "unknown"


def _to_job(posting: dict[str, Any]) -> Job:
    published = posting.get("pubDate")
    region = " ".join((posting.get("jobGeo") or "unspecified").split())
    # Seniority goes into the description so the description rules can reject it with a reason.
    description = f"Seniority: {_seniority(posting.get('jobLevel') or '')}.\n" + (
        posting.get("jobDescription") or ""
    )
    return Job(
        source=JobicySource.name,
        ats="jobicy",
        ats_job_id=str(posting["id"]),
        company=posting.get("companyName", ""),
        title=posting.get("jobTitle", ""),
        location=f"Remote - {region}",
        url=posting.get("url", ""),
        remote=True,
        posted_at=datetime.fromisoformat(published) if published else None,
        description=description,
    )
