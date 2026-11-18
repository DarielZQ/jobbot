"""Discovery source interface."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable

from jobbot.core.http import HttpClient
from jobbot.core.models import Job
from jobbot.matching.normalize import normalize_text

_JSON_LD = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)


def job_posting(page: str) -> dict:
    """The schema.org JobPosting of a job page (iCIMS, Experian...), or {}."""
    for block in _JSON_LD.findall(page):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
    return {}


class SourceNotConfigured(Exception):
    """The source needs a setup step from the user (credentials, login). Not an error."""


def require(value: object, setting: str) -> None:
    """Sources that search by country stop with a clear message when none is configured."""
    if value in ("", None):
        raise SourceNotConfigured(f"falta {setting} (completa `region` en config/settings.yaml)")


def scoped_remote(location: str, scope: str) -> str:
    """A bare "Remote" says nothing about where: `scope` is what it means at that company
    (`remote_scope` in targets.yaml, e.g. "Worldwide"). Any other location stays as it is."""
    if scope and normalize_text(location) in ("", "remote", "remoto", "fully remote"):
        return f"Remote - {scope}"
    return location


class Source:
    """A source lists postings cheaply; `enrich` fetches details only for promising ones."""

    name: str
    # Sources that share a site's bot protection (every Workday tenant) name the same platform:
    # a bot check stops the rest of the platform for that run (ADR-032). "" = its own platform.
    platform: str = ""
    # Some APIs ask callers to query rarely (e.g. Remotive: max ~4 times a day). Counted from
    # the platform's last query, blocked ones too.
    min_hours_between_runs: float = 0
    # At most one query per calendar day (local time) for the whole platform, blocked ones too:
    # the first run of the day makes it and later searches skip it (ADR-032).
    once_a_day: bool = False
    # Set by `fetch` once it has listed every open posting of the site, not just the newest ones
    # or the first pages: a known job missing from that listing was taken down (ADR-026).
    # Feeds, searches and email alerts never set it.
    listing_complete: bool = False

    def __init__(self, client: HttpClient | None) -> None:
        self.client = client

    def fetch(self) -> Iterable[Job]:
        raise NotImplementedError

    def enrich(self, job: Job) -> Job:
        return job
