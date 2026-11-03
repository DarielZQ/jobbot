"""Discovery source interface."""

from __future__ import annotations

from collections.abc import Iterable

from jobbot.core.http import HttpClient
from jobbot.core.models import Job


class SourceNotConfigured(Exception):
    """The source needs a setup step from the user (credentials, login). Not an error."""


def require(value: object, setting: str) -> None:
    """Sources that search by country stop with a clear message when none is configured."""
    if value in ("", None):
        raise SourceNotConfigured(f"falta {setting} (completa `region` en config/settings.yaml)")


class Source:
    """A source lists postings cheaply; `enrich` fetches details only for promising ones."""

    name: str
    # Some APIs ask callers to query rarely (e.g. Remotive: max ~4 times a day).
    min_hours_between_runs: float = 0

    def __init__(self, client: HttpClient | None) -> None:
        self.client = client

    def fetch(self) -> Iterable[Job]:
        raise NotImplementedError

    def enrich(self, job: Job) -> Job:
        return job
