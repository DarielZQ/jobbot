"""Jibe career sites (<company>.jibeapply.com): public jobs JSON API.

GET https://{host}/api/jobs?page=N&limit=100   (robots.txt: Allow /, crawl-delay 5)
The API ignores the country filter we tried, so jobs are filtered here by `country`.
See docs/platforms/job-boards.md.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from jobbot.config import JibeTarget
from jobbot.core.http import HttpClient
from jobbot.core.models import Job
from jobbot.discovery.base import Source, require

PAGE_SIZE = 100
MAX_PAGES = 10


class JibeSource(Source):
    def __init__(self, client: HttpClient, target: JibeTarget) -> None:
        super().__init__(client)
        self.target = target
        self.name = f"jibe:{target.company.lower().replace(' ', '')}"

    def fetch(self) -> Iterable[Job]:
        require(self.target.country, "el país (region.country)")
        wanted = self.target.country.lower()
        collected = 0
        for page in range(1, MAX_PAGES + 1):
            data = self.client.get_json(
                f"https://{self.target.host}/api/jobs?page={page}&limit={PAGE_SIZE}"
            )
            jobs = data.get("jobs") or []
            collected += len(jobs)
            for item in jobs:
                posting = item.get("data") or {}
                if (posting.get("country") or "").lower() == wanted:
                    yield self._to_job(posting)
            if not jobs or collected >= int(data.get("totalCount") or 0):
                return

    def _to_job(self, posting: dict[str, Any]) -> Job:
        slug = posting.get("slug") or posting.get("req_id")
        posted = posting.get("posted_date")
        return Job(
            source=self.name,
            ats="jibe",
            ats_job_id=f"{self.target.host}:{posting.get('req_id') or slug}",
            company=self.target.company,
            title=posting.get("title", ""),
            location=posting.get("full_location") or self.target.country,
            url=f"https://{self.target.host}/jobs/{slug}",
            remote="remote" in (posting.get("location_type") or "").lower(),
            posted_at=_parse(posted),
            description="\n".join(
                filter(None, [posting.get("description"), posting.get("qualifications")])
            ),
        )


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("+0000", "+00:00"))
    except ValueError:
        return None
