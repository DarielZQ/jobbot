"""Cross-source duplicate detection."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from jobbot.core.db import JobRow
from jobbot.core.models import Job
from jobbot.matching.normalize import normalize_company, normalize_text, normalize_title

# A title alone identifies an opening only when it is specific enough: "Soporte técnico" from
# an unnamed company may be anyone's, "Solution Support Specialist" much less so.
_MIN_TITLE_WORDS_WITHOUT_COMPANY = 3


def dedupe_key(job: Job) -> str:
    """Same company + title + first location token => same opening, whatever the source."""
    city = normalize_text(job.location.split(",")[0]) if job.location else ""
    raw = "|".join((normalize_company(job.company), normalize_title(job.title), city))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _placeholder(company: str) -> bool:
    """Alert emails without the company name store "(Indeed)" instead."""
    return company.startswith("(") and company.endswith(")")


def applied_twins(pending: Iterable[JobRow], applied: Iterable[JobRow]) -> dict[int, JobRow]:
    """Open jobs that look like one the candidate already applied to.

    Looser than `dedupe_key`, which keeps the location: the same posting arrives as "Tres Ríos"
    from one site and "La Unión" from another, or as "Remote - Anywhere" and "Remote -
    Worldwide". A warning, not a filter: the same title may truly be two openings.
    """
    by_company: dict[tuple[str, str], JobRow] = {}
    by_title: dict[str, JobRow] = {}  # any applied job, for an unnamed open one
    by_title_unnamed: dict[str, JobRow] = {}  # unnamed applied jobs, for a named open one
    for job in applied:
        title = normalize_title(job.title)
        if not _placeholder(job.company):
            by_company.setdefault((normalize_company(job.company), title), job)
        if len(title.split()) >= _MIN_TITLE_WORDS_WITHOUT_COMPANY:
            by_title.setdefault(title, job)
            if _placeholder(job.company):
                by_title_unnamed.setdefault(title, job)

    twins: dict[int, JobRow] = {}
    for job in pending:
        title = normalize_title(job.title)
        twin = by_company.get((normalize_company(job.company), title))
        if twin is None and len(title.split()) >= _MIN_TITLE_WORDS_WITHOUT_COMPANY:
            # With no company on one side, the title is all there is to compare.
            twin = (by_title if _placeholder(job.company) else by_title_unnamed).get(title)
        if twin is not None and twin.id != job.id:
            twins[job.id] = twin
    return twins
