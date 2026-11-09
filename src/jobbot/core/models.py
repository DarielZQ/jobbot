"""Common domain models shared by every source and stage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field


def as_utc(moment: datetime) -> datetime:
    """Sites that give only a date, or a time without offset: read it as UTC."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def posted_within(
    posted_at: datetime | None, hours: float, seen_at: datetime | None = None
) -> bool:
    """Posted at most `hours` before `seen_at` (now, unless given). Unknown dates are not."""
    if posted_at is None:
        return False
    seen = as_utc(seen_at) if seen_at else datetime.now(UTC)
    return seen - as_utc(posted_at) <= timedelta(hours=hours)


class Job(BaseModel):
    """A job posting normalized from any source."""

    source: str = Field(description="Discovery source, e.g. 'workday:intel'")
    ats: str = Field(description="ATS family: workday | greenhouse | lever | ...")
    ats_job_id: str = Field(description="Stable id within the ATS/tenant")
    company: str
    title: str
    location: str = ""
    url: str
    remote: bool = False
    posted_at: datetime | None = None
    # From a relative age ("Posted 3 Days Ago") or the alert email's date, not the site's own date
    posted_approx: bool = False
    # Suggested by the site, not matched by a search the candidate set up: it can be months old
    recommended: bool = False
    description: str = ""
