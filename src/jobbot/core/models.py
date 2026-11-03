"""Common domain models shared by every source and stage."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


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
    description: str = ""
