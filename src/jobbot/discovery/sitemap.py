"""Company career sites read through their sitemap.xml (Experian: jobs.experian.com).

List:   GET {sitemap} (a sitemap index is followed) -> job URLs that contain `match`
        ".../job/<title>-in-<place>-jid-<id>": title and place come from the URL
Detail: GET {job url} -> schema.org JobPosting (JSON-LD): title, date, place, description
Some sites disallow their search page in robots.txt but publish a sitemap for crawlers and allow
the job pages: Experian disallows /jobs? and allows /job/ (ADR-031). Only jobs that pass the
title and location filters get their page (`enrich`). See docs/platforms/job-boards.md.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import datetime
from urllib.parse import unquote, urlsplit

from jobbot.config import SitemapTarget
from jobbot.core.http import HttpClient
from jobbot.core.models import Job
from jobbot.discovery.base import Source, job_posting

MAX_SITEMAPS = 10
_LOC = "{http://www.sitemaps.org/schemas/sitemap/0.9}loc"
# "<title>-in-<place>-jid-<id>" (Experian); a trailing number alone is the id elsewhere
_SLUG = re.compile(r"^(?P<body>.+?)(?:-jid)?-(?P<id>\d+)$")


def from_slug(url: str) -> tuple[str, str, str]:
    """(title, place, id) from the last part of a job URL. The place follows the last "-in-":
    "engineer-in-training-in-heredia-costa-rica" is "Engineer in training", "Heredia Costa Rica"."""
    slug = unquote(urlsplit(url).path.rstrip("/").rpartition("/")[2])
    match = _SLUG.match(slug)
    body, job_id = (match.group("body"), match.group("id")) if match else (slug, url)
    title, _, place = body.rpartition("-in-") if "-in-" in body else (body, "", "")
    return title.replace("-", " ").capitalize(), place.replace("-", " ").title(), job_id


def _locs(xml: str) -> list[str]:
    return [(node.text or "").strip() for node in ET.fromstring(xml).iter(_LOC)]


class SitemapSource(Source):
    def __init__(self, client: HttpClient, target: SitemapTarget) -> None:
        super().__init__(client)
        self.target = target
        self.host = urlsplit(target.sitemap).netloc
        self.name = f"sitemap:{target.company.lower().replace(' ', '')}"

    def fetch(self) -> Iterable[Job]:
        xml = self.client.get_text(self.target.sitemap, accept="application/xml, text/xml")
        urls = _locs(xml)
        if ET.fromstring(xml).tag.endswith("sitemapindex"):
            urls = [
                url
                for child in urls[:MAX_SITEMAPS]
                for url in _locs(self.client.get_text(child, accept="application/xml, text/xml"))
            ]
        wanted = self.target.match.lower()
        for url in urls:
            if wanted in url.lower():
                yield self._to_job(url)
        self.listing_complete = True

    def enrich(self, job: Job) -> Job:
        posting = job_posting(self.client.get_text(job.url, accept="text/html"))
        places = posting.get("jobLocation") or []
        places = places if isinstance(places, list) else [places]
        location = " / ".join(
            filter(None, ((p.get("address") or {}).get("addressLocality") for p in places))
        )
        posted = posting.get("datePosted")
        return job.model_copy(
            update={
                "title": posting.get("title") or job.title,
                "location": location or job.location,
                "description": posting.get("description", ""),
                "posted_at": datetime.fromisoformat(posted) if posted else job.posted_at,
            }
        )

    def _to_job(self, url: str) -> Job:
        title, place, job_id = from_slug(url)
        return Job(
            source=self.name,
            ats="sitemap",
            ats_job_id=f"{self.host}:{job_id}",
            company=self.target.company,
            title=title,
            location=place,
            url=url,
            remote="remote" in f"{title} {place}".lower(),
        )
