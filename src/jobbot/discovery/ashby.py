"""Ashby public job posting API (no auth). See docs/platforms/greenhouse-lever.md."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from jobbot.config import AshbyTarget
from jobbot.core.http import HttpClient
from jobbot.core.models import Job
from jobbot.discovery.base import Source, scoped_remote


class AshbySource(Source):
    def __init__(self, client: HttpClient, target: AshbyTarget) -> None:
        super().__init__(client)
        self.target = target
        self.name = f"ashby:{target.board}"

    def fetch(self) -> Iterable[Job]:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{self.target.board}"
        for posting in self.client.get_json(url).get("jobs") or []:
            if posting.get("isListed") is False:
                continue
            places = [posting.get("location", "")]
            places += [p.get("location", "") for p in posting.get("secondaryLocations") or []]
            location = ", ".join(dict.fromkeys(p for p in places if p))
            published = posting.get("publishedAt")
            yield Job(
                source=self.name,
                ats="ashby",
                ats_job_id=f"{self.target.board}:{posting['id']}",
                company=self.target.company,
                title=posting.get("title", "").strip(),
                location=scoped_remote(location, self.target.remote_scope),
                url=posting.get("jobUrl", ""),
                remote=bool(posting.get("isRemote")) or posting.get("workplaceType") == "Remote",
                posted_at=datetime.fromisoformat(published) if published else None,
                description=posting.get("descriptionPlain", ""),
            )
