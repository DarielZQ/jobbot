"""Oracle Recruiting Cloud career sites (<pod>.fa.<region>.oraclecloud.com): the public REST API
the site's own pages use. Oracle and Emerson publish there.

Place:  GET {host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions
          ?onlyData=true&finder=findReqs;siteNumber=<site>,facetsList=LOCATIONS,keyword="<país>"
        -> the id of the location facet named exactly like the country
List:   same resource, finder=findReqs;siteNumber=<site>,locationId=<id>,limit=25,offset=N
Detail: GET {host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails
          ?expand=all&onlyData=true&finder=ById;Id="<id>",siteNumber=<site>
These hosts have no robots.txt (ADR-031). Only jobs that pass the filters get their details
(`enrich`). See docs/platforms/job-boards.md.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any
from urllib.parse import quote

from jobbot.config import OracleHcmTarget
from jobbot.core.http import HttpClient
from jobbot.core.models import Job
from jobbot.discovery.base import Source, require

PAGE_SIZE = 25
MAX_PAGES = 20
_API = "/hcmRestApi/resources/latest"


class OracleHcmSource(Source):
    def __init__(self, client: HttpClient, target: OracleHcmTarget) -> None:
        super().__init__(client)
        self.target = target
        self.name = f"oraclehcm:{target.company.lower().replace(' ', '')}"

    def fetch(self) -> Iterable[Job]:
        require(self.target.country, "el país (region.country)")
        location_id = self.target.location_id or self._country_location()
        if not location_id:
            raise ValueError(
                f"el sitio no tiene una ubicación llamada «{self.target.country}»: no publica "
                "vacantes en ese país o la nombra de otra forma (location_id en targets.yaml)"
            )
        offset = 0
        for _ in range(MAX_PAGES):
            search = self._search(f"locationId={location_id},limit={PAGE_SIZE},offset={offset},"
                                  "sortBy=POSTING_DATES_DESC")  # fmt: skip
            jobs = search.get("requisitionList") or []
            yield from (self._to_job(posting) for posting in jobs)
            offset += len(jobs)
            if not jobs or offset >= int(search.get("TotalJobsCount") or 0):
                self.listing_complete = True
                return

    def enrich(self, job: Job) -> Job:
        job_id = job.ats_job_id.rpartition(":")[2]
        url = (
            f"https://{self.target.host}{_API}/recruitingCEJobRequisitionDetails?expand=all"
            f'&onlyData=true&finder=ById;Id="{job_id}",siteNumber={self.target.site}'
        )
        details = (self.client.get_json(url).get("items") or [{}])[0]
        parts = (
            "ExternalDescriptionStr",
            "ExternalResponsibilitiesStr",
            "ExternalQualificationsStr",
        )
        return job.model_copy(
            update={"description": "\n".join(filter(None, (details.get(k) for k in parts)))}
        )

    def _country_location(self) -> int | None:
        """The location facet named exactly like the country (Emerson: 300000000228624)."""
        search = self._search(f'facetsList=LOCATIONS,limit=1,keyword="{self.target.country}"')
        for facet in search.get("locationsFacet") or []:
            if (facet.get("Name") or "").lower() == self.target.country.lower():
                return int(facet["Id"])
        return None

    def _search(self, finder: str) -> dict[str, Any]:
        url = (
            f"https://{self.target.host}{_API}/recruitingCEJobRequisitions?onlyData=true"
            "&expand=requisitionList.secondaryLocations"
            f"&finder=findReqs;siteNumber={self.target.site},{quote(finder, safe='=,;')}"
        )
        return (self.client.get_json(url).get("items") or [{}])[0]

    def _to_job(self, posting: dict[str, Any]) -> Job:
        places = [posting.get("PrimaryLocation") or ""]
        places += [place.get("Name") or "" for place in posting.get("secondaryLocations") or []]
        workplace = f"{posting.get('WorkplaceTypeCode')} {posting.get('WorkplaceType')}".lower()
        posted = posting.get("PostedDate")
        return Job(
            source=self.name,
            ats="oraclehcm",
            ats_job_id=f"{self.target.host}:{posting['Id']}",
            company=self.target.company,
            title=posting.get("Title", ""),
            # "Escazú, San José, Costa Rica"; a job open in several places lists them all
            location=" / ".join(filter(None, places)),
            url=f"https://{self.target.host}/hcmUI/CandidateExperience/en/sites/"
            f"{self.target.site}/job/{posting['Id']}",
            remote="remote" in workplace,
            posted_at=datetime.fromisoformat(f"{posted}T00:00:00+00:00") if posted else None,
        )
