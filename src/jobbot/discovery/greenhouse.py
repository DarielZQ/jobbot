"""Greenhouse public Job Board API (no auth). See docs/platforms/greenhouse.md."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from jobbot.config import GreenhouseTarget
from jobbot.core.http import HttpClient
from jobbot.core.models import Job
from jobbot.discovery.base import Source
from jobbot.matching.normalize import normalize_text


class GreenhouseSource(Source):
    def __init__(self, client: HttpClient, target: GreenhouseTarget) -> None:
        super().__init__(client)
        self.target = target
        self.name = f"greenhouse:{target.token}"

    def fetch(self) -> Iterable[Job]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{self.target.token}/jobs?content=true"
        data = self.client.get_json(url)
        for posting in data.get("jobs", []):
            location = (posting.get("location") or {}).get("name", "")
            updated = posting.get("updated_at")
            yield Job(
                source=self.name,
                ats="greenhouse",
                ats_job_id=f"{self.target.token}:{posting['id']}",
                company=self.target.company,
                title=posting.get("title", ""),
                location=location,
                url=posting.get("absolute_url", ""),
                remote="remote" in normalize_text(location),
                posted_at=datetime.fromisoformat(updated) if updated else None,
                description=posting.get("content", ""),
            )
