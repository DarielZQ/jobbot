"""amazon.jobs: the public search JSON its own site uses (no login).

GET https://www.amazon.jobs/en/search.json?normalized_country_code[]=<ISO alpha-3>
    &result_limit=100&offset=N
See docs/platforms/job-boards.md.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from jobbot.config import AmazonTarget
from jobbot.core.http import HttpClient
from jobbot.core.models import Job
from jobbot.discovery.base import Source, require

PAGE_SIZE = 100
MAX_PAGES = 10


class AmazonSource(Source):
    def __init__(self, client: HttpClient, target: AmazonTarget) -> None:
        super().__init__(client)
        self.target = target
        self.name = f"amazon:{target.country_code.lower()}"

    def fetch(self) -> Iterable[Job]:
        require(self.target.country_code, "el código de país (region.country_code)")
        for page in range(MAX_PAGES):
            offset = page * PAGE_SIZE
            url = (
                "https://www.amazon.jobs/en/search.json"
                f"?normalized_country_code%5B%5D={self.target.country_code}"
                f"&result_limit={PAGE_SIZE}&offset={offset}"
            )
            data = self.client.get_json(url)
            jobs = data.get("jobs") or []
            for posting in jobs:
                yield self._to_job(posting)
            if not jobs or offset + PAGE_SIZE >= int(data.get("hits") or 0):
                return

    def _to_job(self, posting: dict[str, Any]) -> Job:
        location = posting.get("normalized_location") or posting.get("location") or ""
        country = self.target.country or self.target.country_code
        if country.lower() not in location.lower():
            # amazon.jobs reports the country as an ISO code ("San Jose, San Jose, CRI").
            location = f"{location}, {country}".strip(", ")
        # Basic qualifications hold the hard requirements (years of experience); preferred
        # ones are optional and would wrongly trigger the experience filter.
        description = "\n".join(
            filter(None, [posting.get("description"), posting.get("basic_qualifications")])
        )
        return Job(
            source=self.name,
            ats="amazon",
            ats_job_id=str(posting.get("id_icims") or posting.get("id")),
            company=self.target.company,
            title=(posting.get("title") or "").strip(),
            location=location,
            url=f"https://www.amazon.jobs{posting.get('job_path', '')}",
            posted_at=_parse_date(posting.get("posted_date")),
            description=description,
        )


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%B %d, %Y")
    except ValueError:
        return None
