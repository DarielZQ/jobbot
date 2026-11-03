"""Workday career sites: the public JSON endpoint the site itself uses (no login).

List:   POST https://{host}/wday/cxs/{tenant}/{site}/jobs
Detail: GET  https://{host}/wday/cxs/{tenant}/{site}{externalPath}
See docs/platforms/workday.md.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from jobbot.config import WorkdayTarget
from jobbot.core.http import HttpClient
from jobbot.core.models import Job
from jobbot.discovery.base import Source, require
from jobbot.matching.normalize import normalize_text

PAGE_SIZE = 20  # Workday rejects larger pages
MAX_PAGES = 25


def find_country_facet(facets: list[dict[str, Any]], country: str) -> tuple[str, list[str]] | None:
    """Return (facetParameter, ids) whose descriptors mention the country.

    Workday nests facets differently per tenant, so walk the whole tree. When several
    parameters match, prefer a country-level one; otherwise the one with most ids.
    """
    wanted = normalize_text(country)
    found: dict[str, list[str]] = {}

    def walk(nodes: list[dict[str, Any]], parameter: str) -> None:
        for node in nodes:
            current = node.get("facetParameter", parameter)
            if "id" in node and wanted in normalize_text(node.get("descriptor", "")):
                found.setdefault(parameter, []).append(node["id"])
            if isinstance(node.get("values"), list):
                walk(node["values"], current)

    walk(facets, "")
    found.pop("", None)
    if not found:
        return None
    country_params = [p for p in found if "country" in p.lower()]
    parameter = country_params[0] if country_params else max(found, key=lambda p: len(found[p]))
    return parameter, found[parameter]


class WorkdaySource(Source):
    def __init__(self, client: HttpClient, target: WorkdayTarget) -> None:
        super().__init__(client)
        self.target = target
        self.name = f"workday:{target.tenant}"
        self._api = f"https://{target.host}/wday/cxs/{target.tenant}/{target.site}"
        self._public = f"https://{target.host}/{target.site}"

    def fetch(self) -> Iterable[Job]:
        require(self.target.country, "el país (region.country)")
        first = self._page(applied_facets={}, offset=0, search_text="")
        facet = find_country_facet(first.get("facets", []), self.target.country)
        if facet:
            parameter, ids = facet
            yield from self._paginate({parameter: ids}, search_text="", facet_applied=True)
        else:
            # No location facet: search by country name and rely on location rules.
            yield from self._paginate({}, search_text=self.target.country, facet_applied=False)

    def enrich(self, job: Job) -> Job:
        external_path = job.url.removeprefix(self._public)
        data = self.client.get_json(f"{self._api}{external_path}")
        description = data.get("jobPostingInfo", {}).get("jobDescription", "")
        return job.model_copy(update={"description": description})

    def _paginate(
        self, applied_facets: dict[str, list[str]], *, search_text: str, facet_applied: bool
    ) -> Iterator[Job]:
        total: int | None = None
        for page in range(MAX_PAGES):
            offset = page * PAGE_SIZE
            data = self._page(applied_facets, offset=offset, search_text=search_text)
            if total is None:
                total = int(data.get("total") or 0)
            postings = data.get("jobPostings") or []
            for posting in postings:
                # Now and then a posting comes without a link (seen 2026-10-28): nothing to open.
                if posting.get("externalPath"):
                    yield self._to_job(posting, facet_applied)
            if not postings or offset + PAGE_SIZE >= total:
                return

    def _page(
        self, applied_facets: dict[str, list[str]], *, offset: int, search_text: str
    ) -> dict[str, Any]:
        payload = {
            "appliedFacets": applied_facets,
            "limit": PAGE_SIZE,
            "offset": offset,
            "searchText": search_text,
        }
        return self.client.post_json(f"{self._api}/jobs", payload)

    def _to_job(self, posting: dict[str, Any], facet_applied: bool) -> Job:
        external_path = posting["externalPath"]
        bullets = posting.get("bulletFields") or []
        requisition = bullets[0] if bullets else external_path.rsplit("_", 1)[-1]
        location = posting.get("locationsText", "")
        if facet_applied and normalize_text(self.target.country) not in normalize_text(location):
            # e.g. "2 Locations": the facet already guarantees the country.
            location = f"{location} | {self.target.country}".strip(" |")
        return Job(
            source=self.name,
            ats="workday",
            ats_job_id=f"{self.target.tenant}:{requisition}",
            company=self.target.company,
            title=posting.get("title", ""),
            location=location,
            url=f"{self._public}{external_path}",
            remote="remote" in normalize_text(posting.get("remoteType", "")),
        )
