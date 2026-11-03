"""Lever public Postings API (no auth). See docs/platforms/lever.md."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from jobbot.config import LeverTarget
from jobbot.core.http import HttpClient
from jobbot.core.models import Job
from jobbot.discovery.base import Source


class LeverSource(Source):
    def __init__(self, client: HttpClient, target: LeverTarget) -> None:
        super().__init__(client)
        self.target = target
        self.name = f"lever:{target.slug}"

    def fetch(self) -> Iterable[Job]:
        url = f"https://api.lever.co/v0/postings/{self.target.slug}?mode=json"
        for posting in self.client.get_json(url):
            categories = posting.get("categories") or {}
            locations = categories.get("allLocations") or [categories.get("location", "")]
            created = posting.get("createdAt")
            description = "\n".join(
                filter(None, [posting.get("descriptionPlain"), posting.get("additionalPlain")])
            )
            yield Job(
                source=self.name,
                ats="lever",
                ats_job_id=f"{self.target.slug}:{posting['id']}",
                company=self.target.company,
                title=posting.get("text", ""),
                location=", ".join(filter(None, locations)),
                url=posting.get("hostedUrl", ""),
                remote=posting.get("workplaceType") == "remote",
                posted_at=datetime.fromtimestamp(created / 1000, UTC) if created else None,
                description=description,
            )
