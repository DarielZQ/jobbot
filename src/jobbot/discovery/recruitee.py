"""Recruitee career sites: public offers API (no auth).

GET https://{subdomain}.recruitee.com/api/offers/
See docs/platforms/job-boards.md.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from jobbot.config import RecruiteeTarget
from jobbot.core.http import HttpClient
from jobbot.core.models import Job
from jobbot.discovery.base import Source


class RecruiteeSource(Source):
    def __init__(self, client: HttpClient, target: RecruiteeTarget) -> None:
        super().__init__(client)
        self.target = target
        self.name = f"recruitee:{target.subdomain}"

    def fetch(self) -> Iterable[Job]:
        data = self.client.get_json(f"https://{self.target.subdomain}.recruitee.com/api/offers/")
        for offer in data.get("offers") or []:
            yield self._to_job(offer)

    def _to_job(self, offer: dict[str, Any]) -> Job:
        location = offer.get("location") or ", ".join(
            filter(None, [offer.get("city"), offer.get("country")])
        )
        remote = bool(offer.get("remote"))
        if remote and "remote" not in location.lower():
            location = f"Remote | {location}"
        created = offer.get("published_at") or offer.get("created_at")
        return Job(
            source=self.name,
            ats="recruitee",
            ats_job_id=f"{self.target.subdomain}:{offer['id']}",
            company=offer.get("company_name") or self.target.company,
            title=offer.get("title", ""),
            location=location,
            url=offer.get("careers_url", ""),
            remote=remote,
            posted_at=_parse(created),
            description="\n".join(
                filter(None, [offer.get("description"), offer.get("requirements")])
            ),
        )


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace(" UTC", "+00:00"))
    except ValueError:
        return None
