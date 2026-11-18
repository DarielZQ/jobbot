"""IBM careers: the search API behind ibm.com/careers/search.

POST https://www-api.ibm.com/search/api/v2  (JSON body, filtered by country, paged with from/size)
www-api.ibm.com has no robots.txt rules (it redirects to the home page) and IBM's terms allow
crawlers that follow robots.txt (ADR-031). The job pages (careers.ibm.com, Avature) answer with
an AWS bot check, so JobBot keeps the short summary the search gives and never opens them.
See docs/platforms/job-boards.md.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

from jobbot.config import IbmTarget
from jobbot.core.http import HttpClient
from jobbot.core.models import Job
from jobbot.discovery.base import Source, require

URL = "https://www-api.ibm.com/search/api/v2"
PAGE_SIZE = 50
MAX_PAGES = 10
# field_keyword_05: country · 08: area · 17: work mode · 18: level · 19: place ("Heredia, CR")
_FIELDS = ["title", "url", "description", "dcdate", "field_keyword_05", "field_keyword_08",
           "field_keyword_17", "field_keyword_18", "field_keyword_19"]  # fmt: skip


def search_body(country: str, start: int) -> dict[str, Any]:
    return {
        "appId": "careers",
        "scopes": ["careers2"],
        "query": {"bool": {"must": []}},
        "post_filter": {"bool": {"must": [{"term": {"field_keyword_05": country}}]}},
        "size": PAGE_SIZE,
        "from": start,
        "sort": [{"_score": "desc"}],
        "lang": "zz",
        "localLang": "xx",
        "sm": {"query": "", "lang": "zz"},
        "_source": _FIELDS,
    }


class IbmSource(Source):
    def __init__(self, client: HttpClient, target: IbmTarget) -> None:
        super().__init__(client)
        self.target = target
        self.name = "ibm"

    def fetch(self) -> Iterable[Job]:
        require(self.target.country, "el país (region.country)")
        start = 0
        for _ in range(MAX_PAGES):
            hits = self.client.post_json(URL, search_body(self.target.country, start))["hits"]
            page = hits.get("hits") or []
            yield from (self._to_job(hit.get("_source") or {}) for hit in page)
            start += len(page)
            if not page or start >= int((hits.get("total") or {}).get("value") or 0):
                self.listing_complete = True
                return

    def _to_job(self, posting: dict[str, Any]) -> Job:
        url = posting.get("url", "")
        job_id = (parse_qs(urlsplit(url).query).get("jobId") or [url])[0]
        mode = posting.get("field_keyword_17") or ""
        area, level = posting.get("field_keyword_08"), posting.get("field_keyword_18")
        # The search only gives a summary; area, level and mode help to judge it.
        labels = " · ".join(filter(None, [area, level, mode]))
        summary = "\n".join(filter(None, [labels, posting.get("description", "")]))
        posted = posting.get("dcdate")
        return Job(
            source=self.name,
            ats="ibm",
            ats_job_id=job_id,
            company=self.target.company,
            title=posting.get("title", ""),
            location=posting.get("field_keyword_19") or self.target.country,
            url=url,
            remote="remote" in mode.lower(),
            posted_at=datetime.fromisoformat(posted).replace(tzinfo=UTC) if posted else None,
            description=summary,
        )
