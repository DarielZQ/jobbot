"""Eightfold career sites (Microsoft since 2026): the site's own public search JSON.

List:   GET https://{host}/api/pcsx/search?domain=<domain>&query=&location=<país>&start=N
Detail: GET https://{host}/api/pcsx/position_details?position_id=<id>&domain=<domain>
robots.txt of apply.careers.microsoft.com disallows everything but a few paths, among them
/api/pcsx and /careers (ADR-030). The search matches places loosely (it may return other
countries), so the location filter of search.yaml still applies. Only jobs that pass the
filters get their details (`enrich`). See docs/platforms/job-boards.md.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from jobbot.config import EightfoldTarget
from jobbot.core.http import HttpClient
from jobbot.core.models import Job
from jobbot.discovery.base import Source, require

PAGE_SIZE = 10  # fixed by the site
MAX_PAGES = 20


class EightfoldSource(Source):
    def __init__(self, client: HttpClient, target: EightfoldTarget) -> None:
        super().__init__(client)
        self.target = target
        self.name = f"eightfold:{target.domain.split('.')[0]}"

    def fetch(self) -> Iterable[Job]:
        require(self.target.country, "el país (region.country)")
        start = 0
        for _ in range(MAX_PAGES):
            data = self.client.get_json(
                self._url("search", f"&query=&location={quote(self.target.country)}&start={start}")
            )["data"]
            positions = data.get("positions") or []
            yield from (self._to_job(position) for position in positions)
            start += len(positions)
            if not positions or start >= int(data.get("count") or 0):
                self.listing_complete = True
                return

    def enrich(self, job: Job) -> Job:
        position_id = job.ats_job_id.rpartition(":")[2]
        data = self.client.get_json(self._url("position_details", f"&position_id={position_id}"))
        return job.model_copy(
            update={"description": (data.get("data") or {}).get("jobDescription", "")}
        )

    def _url(self, endpoint: str, query: str) -> str:
        return f"https://{self.target.host}/api/pcsx/{endpoint}?domain={self.target.domain}{query}"

    def _to_job(self, position: dict[str, Any]) -> Job:
        posted = position.get("postedTs") or position.get("creationTs")
        return Job(
            source=self.name,
            ats="eightfold",
            ats_job_id=f"{self.target.domain}:{position['id']}",
            company=self.target.company,
            title=position.get("name", ""),
            # "Costa Rica, San José, San José"; several places for one job are joined
            location=" / ".join(position.get("locations") or []),
            url=f"https://{self.target.host}{position.get('positionUrl') or ''}",
            remote=(position.get("workLocationOption") or "").lower() == "remote",
            posted_at=datetime.fromtimestamp(posted, UTC) if posted else None,
        )
