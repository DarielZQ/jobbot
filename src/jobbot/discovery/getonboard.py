"""Get on Board: public REST API, tech jobs focused on Latin America (no auth).

GET https://www.getonbrd.com/api/v0/search/jobs?query=...&per_page=50&page=N&expand=["company"]
See docs/platforms/job-boards.md.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from jobbot.config import GetOnBoardTarget
from jobbot.core.http import HttpClient
from jobbot.core.models import Job
from jobbot.discovery.base import Source

PER_PAGE = 50
# GET /api/v0/seniorities (stable ids)
SENIORITY = {1: "Sin experiencia", 2: "Junior", 3: "Semi Senior", 4: "Senior", 5: "Expert"}


class GetOnBoardSource(Source):
    name = "getonboard"

    def __init__(self, client: HttpClient, target: GetOnBoardTarget) -> None:
        super().__init__(client)
        self.target = target

    def fetch(self) -> Iterable[Job]:
        seen: set[str] = set()
        expand = quote('["company"]')
        for query in self.target.queries:
            for page in range(1, self.target.max_pages + 1):
                url = (
                    "https://www.getonbrd.com/api/v0/search/jobs"
                    f"?query={quote(query)}&per_page={PER_PAGE}&page={page}&expand={expand}"
                )
                data = self.client.get_json(url)
                for item in data.get("data") or []:
                    if item["id"] not in seen:
                        seen.add(item["id"])
                        yield _to_job(item)
                if page >= int((data.get("meta") or {}).get("total_pages") or 0):
                    break


def _to_job(item: dict[str, Any]) -> Job:
    attrs = item["attributes"]
    modality = attrs.get("remote_modality") or ""
    countries = [c for c in attrs.get("countries") or [] if c != "Remote"]
    if modality == "fully_remote":
        location = "Remote - LATAM (fully remote)"
    else:
        location = ", ".join(countries) or "Company country"
        if modality == "remote_local":
            location = f"{location} (remote, must live in country)"
    seniority_id = int(((attrs.get("seniority") or {}).get("data") or {}).get("id") or 0)
    company = (((attrs.get("company") or {}).get("data") or {}).get("attributes") or {}).get(
        "name", ""
    )
    published = attrs.get("published_at")
    # Seniority goes into the description so the description rules can reject it with a reason.
    description = f"Seniority: {SENIORITY.get(seniority_id, 'unknown')}.\n" + "\n".join(
        filter(None, [attrs.get("description"), attrs.get("functions")])
    )
    return Job(
        source=GetOnBoardSource.name,
        ats="getonboard",
        ats_job_id=item["id"],
        company=company or "(Get on Board)",
        title=attrs.get("title", ""),
        location=location,
        url=(item.get("links") or {}).get("public_url")
        or f"https://www.getonbrd.com/jobs/{item['id']}",
        remote=modality == "fully_remote",
        posted_at=datetime.fromtimestamp(published, UTC) if published else None,
        description=description,
    )
