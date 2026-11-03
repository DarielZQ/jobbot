"""SAP SuccessFactors Career Site Builder: public RSS search feed (no login).

GET {base_url}/services/rss/job/?locale=en_US&keywords=<país>
See docs/platforms/successfactors.md.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlsplit, urlunsplit

from jobbot.config import SuccessFactorsTarget
from jobbot.core.http import HttpClient
from jobbot.core.models import Job
from jobbot.discovery.base import Source, require
from jobbot.matching.normalize import normalize_text

# "Heredia Customer Service Representative (On-Site) (Heredia, Costa Rica, CR)"
_TRAILING_LOCATION = re.compile(r"\s*\(([^()]*)\)\s*$")
_JOB_ID = re.compile(r"/(\d{6,})/?$")


def split_title(raw: str) -> tuple[str, str]:
    """Separate the location suffix Career Site Builder appends to RSS titles."""
    match = _TRAILING_LOCATION.search(raw)
    if not match or "," not in match.group(1):
        return raw.strip(), ""
    return raw[: match.start()].strip(), match.group(1).strip()


def clean_link(link: str) -> str:
    """Drop RSS tracking parameters (feedId, utm_*)."""
    parts = urlsplit(link.strip())
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


class SuccessFactorsSource(Source):
    def __init__(self, client: HttpClient, target: SuccessFactorsTarget) -> None:
        super().__init__(client)
        self.target = target
        host = urlsplit(target.base_url).netloc
        self.name = f"successfactors:{host.split('.')[-2] if '.' in host else host}"

    def fetch(self) -> Iterable[Job]:
        require(self.target.keywords, "el país a buscar (region.country)")
        base = self.target.base_url.rstrip("/")
        url = (
            f"{base}/services/rss/job/?locale={self.target.locale}"
            f"&keywords={quote(self.target.keywords)}"
        )
        xml = self.client.get_text(url, accept="application/rss+xml, application/xml")
        root = ET.fromstring(xml)
        for item in root.iterfind("./channel/item"):
            title, location = split_title(item.findtext("title", ""))
            link = clean_link(item.findtext("link", ""))
            match = _JOB_ID.search(urlsplit(link).path)
            job_id = match.group(1) if match else link
            published = item.findtext("pubDate")
            yield Job(
                source=self.name,
                ats="successfactors",
                ats_job_id=f"{urlsplit(base).netloc}:{job_id}",
                company=self.target.company,
                title=title,
                location=location,
                url=link,
                remote="remote" in normalize_text(f"{title} {location}"),
                posted_at=parsedate_to_datetime(published) if published else None,
                description=item.findtext("description", ""),
            )
