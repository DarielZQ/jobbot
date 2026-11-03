"""Himalayas: public remote-jobs search API (no auth).

GET https://himalayas.app/jobs/api/search?q=...&country=Costa%20Rica&page=N
API terms: apply through `applicationLink` unchanged, show Himalayas as the source, do not pass
the listings on to other job boards. Requests without a key share one public allowance, so the
bot asks a few queries and waits `min_hours_between_runs`. See docs/platforms/job-boards.md.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from jobbot.config import HimalayasTarget
from jobbot.core.http import HttpClient
from jobbot.core.models import Job
from jobbot.discovery.base import Source, require

API = "https://himalayas.app/jobs/api/search"
_ENTRY_LEVELS = {"Entry-level", "Mid-level"}


class HimalayasSource(Source):
    name = "himalayas"

    def __init__(self, client: HttpClient, target: HimalayasTarget) -> None:
        super().__init__(client)
        self.target = target
        self.min_hours_between_runs = target.min_hours_between_runs

    def fetch(self) -> Iterable[Job]:
        require(self.target.country, "el país (region.country)")
        seen: set[str] = set()
        country = quote(self.target.country)
        for query in self.target.queries:
            for page in range(1, self.target.max_pages + 1):
                url = f"{API}?q={quote(query)}&country={country}&page={page}"
                postings = self.client.get_json(url).get("jobs") or []
                for posting in postings:
                    guid = posting.get("guid") or posting.get("applicationLink") or ""
                    if guid and guid not in seen and self._open_to_candidate(posting):
                        seen.add(guid)
                        yield _to_job(posting, guid, self.target.country)
                # Pages can hold fewer than 20 jobs before the end: stop only on an empty one.
                if not postings:
                    break

    def _open_to_candidate(self, posting: dict[str, Any]) -> bool:
        """Himalayas' rule: no country list or one that includes the country, and a time zone
        list that includes its standard offset."""
        countries = posting.get("locationRestrictions") or []
        offsets = posting.get("timezoneRestrictions") or []
        return (not countries or self.target.country in countries) and (
            not offsets or self.target.utc_offset in offsets
        )


def _to_job(posting: dict[str, Any], guid: str, country: str) -> Job:
    levels = set(posting.get("seniority") or [])
    seniority = "Senior" if levels and not levels & _ENTRY_LEVELS else ", ".join(sorted(levels))
    restricted = country in (posting.get("locationRestrictions") or [])
    published = posting.get("pubDate")
    # Seniority goes into the description so the description rules can reject it with a reason.
    description = f"Seniority: {seniority or 'unknown'}.\n" + (posting.get("description") or "")
    return Job(
        source=HimalayasSource.name,
        ats="himalayas",
        ats_job_id=guid,
        company=posting.get("companyName", ""),
        title=posting.get("title", ""),
        location=f"Remote - {country if restricted else 'Worldwide'}",
        url=posting.get("applicationLink") or guid,
        remote=True,
        posted_at=datetime.fromtimestamp(published, UTC) if published else None,
        description=description,
    )
