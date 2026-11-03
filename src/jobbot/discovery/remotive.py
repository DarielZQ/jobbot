"""Remotive: public remote-jobs API (no auth).

GET https://remotive.com/api/remote-jobs?category=customer-support
Terms: at most ~4 requests a day, link back to the Remotive URL, do not republish.
The pipeline enforces `min_hours_between_runs`. See docs/platforms/job-boards.md.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any
from urllib.parse import quote

from jobbot.config import RemotiveTarget
from jobbot.core.http import HttpClient
from jobbot.core.models import Job
from jobbot.discovery.base import Source


class RemotiveSource(Source):
    name = "remotive"

    def __init__(self, client: HttpClient, target: RemotiveTarget) -> None:
        super().__init__(client)
        self.target = target
        self.min_hours_between_runs = target.min_hours_between_runs

    def fetch(self) -> Iterable[Job]:
        seen: set[int] = set()
        for category in self.target.categories:
            url = f"https://remotive.com/api/remote-jobs?category={quote(category)}"
            for posting in self.client.get_json(url).get("jobs") or []:
                if posting["id"] not in seen:
                    seen.add(posting["id"])
                    yield _to_job(posting)


def _to_job(posting: dict[str, Any]) -> Job:
    published = posting.get("publication_date")
    region = posting.get("candidate_required_location") or "unspecified"
    return Job(
        source=RemotiveSource.name,
        ats="remotive",
        ats_job_id=str(posting["id"]),
        company=posting.get("company_name", ""),
        title=posting.get("title", ""),
        location=f"Remote - {region}",
        url=posting.get("url", ""),
        remote=True,
        posted_at=datetime.fromisoformat(published) if published else None,
        description=posting.get("description", ""),
    )
