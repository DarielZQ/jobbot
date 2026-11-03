"""Applications confirmed by email (ADR-018).

When the candidate applies on LinkedIn, Indeed or CompuTrabajo, the site emails a confirmation.
Reading it marks the job as applied, so it leaves the pending list and later copies from other
sources get the "Ya postulaste" flag. Read-only, like the alert feeds: the bot never visits the
sites, it only reads emails they already sent.

What each site says about the job it confirms:
- LinkedIn: the posting itself (title, company, place and its /jobs/view/<id> link), then
  "similar jobs" that are left alone.
- Indeed: title, company and place, without a job key.
- CompuTrabajo: only the title, in the subject. The jobs inside are recommendations.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from jobbot.core import db
from jobbot.core.db import JobRow
from jobbot.core.models import Job
from jobbot.core.state import Status
from jobbot.discovery.base import Source
from jobbot.discovery.email_alerts import MailReader, _clean, parse_linkedin
from jobbot.mail.gmail import MailMessage
from jobbot.matching.dedupe import dedupe_key
from jobbot.matching.normalize import normalize_company, normalize_title

NAME = "email:postulaciones"


@dataclass(frozen=True)
class Application:
    """A job the candidate applied to, as a site's confirmation email describes it."""

    site: str  # source suffix of that site's alert feed: "linkedin" -> "email:linkedin"
    title: str
    company: str = ""  # "" when the email does not name it (CompuTrabajo)
    location: str = ""
    job: Job | None = None  # the exact posting, when the email links it (LinkedIn)


# --- Parsers ----------------------------------------------------------------------------------

_LINKEDIN_SENT = re.compile(r"se ha enviado tu solicitud a\s+(.+?)\.?\s*$", re.I)


def parse_linkedin_confirmation(message: MailMessage) -> Application | None:
    """'<name>, se ha enviado tu solicitud a <company>': the first posting is the one applied to."""
    sent = _LINKEDIN_SENT.search(message.subject)
    jobs = parse_linkedin(message, "email:linkedin", "")
    if not sent or not jobs:
        return None
    job = jobs[0]
    # The similar jobs follow; a first posting from another company means the layout changed.
    if normalize_company(job.company) != normalize_company(sent.group(1)):
        return None
    return Application("linkedin", job.title, job.company, job.location, job)


_INDEED_SENT = re.compile(
    r"Postulaci[oó]n enviada.*?<h1[^>]*>(.*?)</h1>.*?<strong[^>]*>(.*?)</strong>([^<]*)",
    re.I | re.S,
)


def parse_indeed_confirmation(message: MailMessage) -> Application | None:
    """'Postulación enviada', then the title (h1) and '<strong>company</strong> - place'."""
    match = _INDEED_SENT.search(message.html)
    if not match:
        return None
    title, company = _clean(match.group(1)), _clean(match.group(2))
    location = re.sub(r"\bnull\b", " ", _clean(match.group(3))).strip(" -")
    return Application("indeed", title, company, " ".join(location.split())) if title else None


_COMPUTRABAJO_SENT = re.compile(r"seguimiento de tu candidatura para el puesto de\s+(.+)$", re.I)


def parse_computrabajo_confirmation(message: MailMessage) -> Application | None:
    match = _COMPUTRABAJO_SENT.search(message.subject)
    return Application("computrabajo", match.group(1).strip()) if match else None


CONFIRMATION_PARSERS: dict[str, Callable[[MailMessage], Application | None]] = {
    "linkedin": parse_linkedin_confirmation,
    "indeed": parse_indeed_confirmation,
    "computrabajo": parse_computrabajo_confirmation,
}


# --- Recording --------------------------------------------------------------------------------


def _placeholder(company: str) -> bool:
    return company.startswith("(") and company.endswith(")")


def _same_opening(app: Application, row: JobRow) -> bool:
    if normalize_title(row.title) != normalize_title(app.title):
        return False
    if app.company and not _placeholder(row.company):
        return normalize_company(row.company) == normalize_company(app.company)
    # A title alone only counts within the site that sent the confirmation.
    return row.source == f"email:{app.site}"


def _mark(conn: sqlite3.Connection, row: JobRow) -> JobRow:
    db.set_status(conn, row.id, Status.SUBMITTED, db.APPLIED_BY_EMAIL)
    return db.get_job(conn, row.id)


def _untouched(row: JobRow) -> bool:
    """The candidate undid an email mark (or reopened the job): their decision stands."""
    return row.status_reason != db.REOPENED_MANUALLY


def record_applications(conn: sqlite3.Connection, apps: Iterable[Application]) -> list[JobRow]:
    """Mark the jobs these applications refer to as applied. Returns the jobs marked or added.

    Running it again over the same emails changes nothing: applied jobs are no longer open.
    """
    changed: list[JobRow] = []
    for app in apps:
        if app.job is not None:
            row = db.find_job(conn, app.job.ats, app.job.ats_job_id)
            if row is None:
                changed.append(_add(conn, app.job))
            elif row.status in (Status.DISCOVERED, Status.SKIPPED) and _untouched(row):
                changed.append(_mark(conn, row))
            continue

        open_rows = db.list_jobs(conn, status=Status.DISCOVERED, limit=100_000)
        matches = [r for r in open_rows if _same_opening(app, r) and _untouched(r)]
        named = [r for r in matches if app.company and not _placeholder(r.company)]
        # Same company and title: the same opening, whatever the source. A title alone must
        # point to a single job.
        for row in named or (matches if len(matches) == 1 else []):
            changed.append(_mark(conn, row))
        job = _job_from(app)
        if (
            not matches
            and app.company
            and db.find_job(conn, job.ats, job.ats_job_id) is None
            and not _already_applied(conn, app)
        ):
            # Applied to something the bot never listed: keep it, so later copies are flagged.
            changed.append(_add(conn, job))
    return changed


def _already_applied(conn: sqlite3.Connection, app: Application) -> bool:
    """Marked by hand already, even if the alert it came from had no company ("(Indeed)")."""
    return any(_same_opening(app, r) for r in db.applied_jobs(conn))


def _job_from(app: Application) -> Job:
    key = hashlib.sha1(f"{app.title}|{app.company}".lower().encode("utf-8")).hexdigest()
    return Job(
        source=NAME,
        ats=app.site,
        ats_job_id=f"applied-{key[:12]}",
        company=app.company,
        title=app.title,
        location=app.location,
        url="",  # the confirmation links only to the site's own tracker
    )


def _add(conn: sqlite3.Connection, job: Job) -> JobRow:
    job_id = db.insert_job(
        conn,
        job.model_copy(update={"source": NAME}),
        dedupe_key=dedupe_key(job),
        status=Status.SUBMITTED,
        status_reason=db.APPLIED_BY_EMAIL,
    )
    return db.get_job(conn, job_id)


# --- Source -----------------------------------------------------------------------------------


class ConfirmationSource(Source):
    """Reads confirmation emails and records the applications (see `run_source`).

    It lists no new jobs: `fetch` is empty and `record` does the work.
    """

    name = NAME

    def __init__(
        self, mail: MailReader, queries: dict[str, str], *, lookback_days: int, max_messages: int
    ) -> None:
        super().__init__(None)
        self._mail = mail
        self._queries = {
            site: f"({query}) newer_than:{lookback_days}d"
            for site, query in queries.items()
            if site in CONFIRMATION_PARSERS
        }
        self._max_messages = max_messages

    def fetch(self) -> Iterable[Job]:
        return []

    def applications(self) -> list[Application]:
        found = []
        for site, query in self._queries.items():
            for message_id in self._mail.search(query, self._max_messages):
                app = CONFIRMATION_PARSERS[site](self._mail.get(message_id))
                if app is not None:
                    found.append(app)
        return found

    def record(self, conn: sqlite3.Connection) -> tuple[int, list[JobRow]]:
        """(confirmations read, jobs marked or added)."""
        apps = self.applications()
        return len(apps), record_applications(conn, apps)
