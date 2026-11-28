"""Discovery run: fetch -> filter -> dedupe -> persist."""

from __future__ import annotations

import contextlib
import sqlite3
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx

from jobbot.config import Targets, resolve
from jobbot.core import db, runlock
from jobbot.core.http import ANTI_BOT, ChallengeError, HttpClient, NotJsonError, error_detail
from jobbot.core.models import Job
from jobbot.core.state import Status
from jobbot.discovery.amazon import AmazonSource
from jobbot.discovery.applications import ConfirmationSource
from jobbot.discovery.ashby import AshbySource
from jobbot.discovery.base import Source, SourceNotConfigured
from jobbot.discovery.deel import DeelSource
from jobbot.discovery.eightfold import EightfoldSource
from jobbot.discovery.elempleo import ElempleoSource
from jobbot.discovery.email_alerts import PARSERS, EmailAlertSource
from jobbot.discovery.getonboard import GetOnBoardSource
from jobbot.discovery.greenhouse import GreenhouseSource
from jobbot.discovery.himalayas import HimalayasSource
from jobbot.discovery.ibm import IbmSource
from jobbot.discovery.icims import ICimsSource
from jobbot.discovery.jibe import JibeSource
from jobbot.discovery.jobicy import JobicySource
from jobbot.discovery.lever import LeverSource
from jobbot.discovery.oracle_hcm import OracleHcmSource
from jobbot.discovery.recruitee import RecruiteeSource
from jobbot.discovery.remotive import RemotiveSource
from jobbot.discovery.replies import MAX_MESSAGES as REPLIES_MAX_MESSAGES
from jobbot.discovery.replies import ReplySource
from jobbot.discovery.sitemap import SitemapSource
from jobbot.discovery.successfactors import SuccessFactorsSource
from jobbot.discovery.workday import WorkdaySource
from jobbot.mail.gmail import GmailClient, access_token
from jobbot.matching.dedupe import dedupe_key, dedupe_key_of, is_placeholder
from jobbot.matching.normalize import normalize_company, normalize_title
from jobbot.matching.rules import TOO_OLD, RuleResult, RuleSet

# Network errors, malformed JSON (ValueError) and malformed XML feeds.
FETCH_ERRORS = (httpx.HTTPError, ValueError, ET.ParseError)


@dataclass
class SourceReport:
    new_matched: int = 0
    new_skipped: int = 0
    seen: int = 0
    skip_reasons: Counter[str] = field(default_factory=Counter)
    error: str = ""
    blocked: bool = False  # the error is a bot check (ADR-003)
    skipped_recent: str = ""
    # Not queried: this source asked for a bot check earlier in the run, on the same platform.
    skipped_blocked: str = ""
    not_configured: str = ""
    # Known open jobs that failed the filters once their details (rescreen) or their company
    # and place (alerts first stored as "(Indeed)") arrived.
    screened_out: int = 0
    # ConfirmationSource only: confirmation emails read and jobs marked (or added) as applied.
    confirmations: int | None = None
    marked_applied: int = 0
    # ReplySource only: employers' replies read, applications closed and questions queued.
    replies: int | None = None
    closed_by_reply: int = 0
    asked: int = 0

    @property
    def skipped(self) -> bool:
        return bool(self.skipped_recent or self.skipped_blocked)


def build_sources(targets: Targets, client: HttpClient) -> list[Source]:
    sources: list[Source] = []
    sources += [WorkdaySource(client, t) for t in targets.workday]
    sources += [GreenhouseSource(client, t) for t in targets.greenhouse]
    sources += [LeverSource(client, t) for t in targets.lever]
    sources += [AshbySource(client, t) for t in targets.ashby]
    sources += [SuccessFactorsSource(client, t) for t in targets.successfactors]
    sources += [AmazonSource(client, t) for t in targets.amazon]
    sources += [RecruiteeSource(client, t) for t in targets.recruitee]
    sources += [ICimsSource(client, t) for t in targets.icims]
    if targets.getonboard:
        sources.append(GetOnBoardSource(client, targets.getonboard))
    if targets.remotive:
        sources.append(RemotiveSource(client, targets.remotive))
    if targets.jobicy:
        sources.append(JobicySource(client, targets.jobicy))
    if targets.himalayas:
        sources.append(HimalayasSource(client, targets.himalayas))
    if targets.elempleo:
        sources.append(ElempleoSource(client, targets.elempleo))
    if targets.deel:
        sources.append(DeelSource(client, targets.deel))
    sources += [JibeSource(client, t) for t in targets.jibe]
    sources += [EightfoldSource(client, t) for t in targets.eightfold]
    sources += [OracleHcmSource(client, t) for t in targets.oraclehcm]
    sources += [SitemapSource(client, t) for t in targets.sitemap]
    if targets.ibm:
        sources.append(IbmSource(client, targets.ibm))
    if (alerts := targets.email_alerts) and alerts.enabled:
        credentials, token = resolve(alerts.credentials_file), resolve(alerts.token_file)
        mail = GmailClient(client, token=lambda: access_token(credentials, token))
        for feed_name in PARSERS:
            if feed := getattr(alerts, feed_name):
                sources.append(
                    EmailAlertSource(
                        feed_name,
                        mail,
                        feed.query,
                        lookback_days=alerts.lookback_days,
                        max_messages=alerts.max_messages,
                        default_location=feed.default_location,
                        remote_scope=feed.remote_scope,
                    )
                )
        if alerts.confirmations:  # last: it can mark jobs the alert feeds just listed
            sources.append(
                ConfirmationSource(
                    mail,
                    alerts.confirmations,
                    lookback_days=alerts.lookback_days,
                    max_messages=alerts.max_messages,
                )
            )
        if alerts.replies:  # after the confirmations: a reply closes only an application
            sources.append(
                ReplySource(
                    mail,
                    alerts.replies,
                    lookback_days=alerts.lookback_days,
                    max_messages=max(alerts.max_messages, REPLIES_MAX_MESSAGES),
                )
            )
    return sources


def rescreen(conn: sqlite3.Connection, rules: RuleSet) -> Counter[str]:
    """Re-apply the current filters to stored jobs, without touching the network.

    Postings whose details were never fetched (skipped before enrichment) are judged on
    title and location only.
    """
    changes: Counter[str] = Counter()
    if rekeyed := rekey(conn):
        changes["rekeyed"] = rekeyed
    for job_id, status, reason, job, seen_at in db.screenable_jobs(conn):
        result = rules.evaluate(job, seen_at)
        if result.ok and rules.too_old(job.posted_at, seen_at):  # undated: since first seen
            days = rules.age_days(job.posted_at, seen_at)
            result = RuleResult(False, f"{TOO_OLD}: {days} días", result.role_family)
        copy = _copy_of(conn, rules, job_id, job) if status is Status.DISCOVERED else None
        if result.ok and copy is not None:
            # Two open copies of one opening, once a new alias gives them the same key: the
            # first one stays, and so does one already applied to.
            reason = f"duplicate_of: {copy}"
            db.set_status(conn, job_id, Status.SKIPPED, reason, result.role_family)
            changes["duplicates"] += 1
        elif result.ok and status is Status.SKIPPED:
            original = db.find_by_dedupe_key(conn, dedupe_key(job))
            # Another copy of the same opening, under another place, already open or applied to
            if original is None and same_opening_elsewhere(conn, rules, job, job_id) is None:
                db.set_status(conn, job_id, Status.DISCOVERED, result.reason, result.role_family)
                changes["reopened"] += 1
        elif not result.ok and status is Status.DISCOVERED:
            db.set_status(conn, job_id, Status.SKIPPED, result.reason, result.role_family)
            changes["newly_skipped"] += 1
        elif result.reason != reason:  # another exclusion, or a note on one that passes
            with conn:
                conn.execute(
                    "UPDATE jobs SET status_reason = ?, role_family = ? WHERE id = ?",
                    (result.reason, result.role_family, job_id),
                )
            changes["reason_updated"] += 1
    return changes


def rekey(conn: sqlite3.Connection) -> int:
    """Compute the stored dedupe keys again, after `company_aliases` (or the normalization)
    changed: copies of one opening then share a key. Returns how many changed."""
    keys = {
        job_id: key
        for job_id, company, title, location, old in db.dedupe_inputs(conn)
        if (key := dedupe_key_of(company, title, location)) != old
    }
    db.set_dedupe_keys(conn, keys)
    return len(keys)


def _copy_of(conn: sqlite3.Connection, rules: RuleSet, job_id: int, job: Job) -> int | None:
    """The job an open one duplicates: an earlier open copy, or a copy already applied to."""
    for original in (
        db.find_by_dedupe_key(conn, dedupe_key(job), other_than=job_id),
        same_opening_elsewhere(conn, rules, job, other_than=job_id),
    ):
        if original is None:
            continue
        other = db.get_job(conn, original)
        still_open = other is not None and other.status is Status.DISCOVERED
        if original < job_id or not still_open:
            return original
    return None


def same_opening_elsewhere(
    conn: sqlite3.Connection, rules: RuleSet, job: Job, other_than: int | None = None
) -> int | None:
    """An open or applied job with the same company and title, first seen within
    `max_age_days`, in another place of the local area: sites name one opening "Sabana", "San
    José" or "Tibás". The dedupe key keeps the place, so it misses these copies (ADR-035)."""
    if is_placeholder(job.company) or not rules.in_local_area(job.location):
        return None
    company, title = normalize_company(job.company), normalize_title(job.title)
    since = datetime.now(UTC) - timedelta(days=rules.max_age_days or 30)
    rows = [*db.list_jobs(conn, status=Status.DISCOVERED, limit=100_000), *db.applied_jobs(conn)]
    copies = [
        row.id
        for row in rows
        if row.id != other_than
        and normalize_company(row.company) == company
        and normalize_title(row.title) == title
        and datetime.fromisoformat(row.first_seen_at) >= since
        and rules.in_local_area(row.location)
    ]
    return min(copies) if copies else None


def expire_old(conn: sqlite3.Connection, rules: RuleSet) -> int:
    """Open jobs that grew older than `max_age_days` go to Descartadas (ADR-023): posted that
    long ago or, without a date, first seen that long ago. Jobs reopened by hand stay."""
    if not rules.max_age_days:
        return 0
    expired = 0
    for row in db.list_jobs(conn, status=Status.DISCOVERED, limit=100_000):
        first_seen = datetime.fromisoformat(row.first_seen_at)
        if row.status_reason == db.REOPENED_MANUALLY or not rules.too_old(row.posted(), first_seen):
            continue
        days = rules.age_days(row.posted(), first_seen)
        db.set_status(conn, row.id, Status.SKIPPED, f"{TOO_OLD}: {days} días", row.role_family)
        expired += 1
    return expired


def _complete_details(
    source: Source, conn: sqlite3.Connection, rules: RuleSet, job: Job, report: SourceReport
) -> None:
    """rescreen works offline, so a job it reopens was judged on title and location only. The
    first run that sees it again fetches its details once and screens it with them."""
    if (job_id := db.open_without_details(conn, job.ats, job.ats_job_id)) is None:
        return
    with contextlib.suppress(*FETCH_ERRORS):
        job = source.enrich(job)
    if not job.description:
        return
    db.set_description(conn, job_id, job.description)
    result = rules.evaluate(job)
    if not result.ok:
        db.set_status(conn, job_id, Status.SKIPPED, result.reason, result.role_family)
        report.screened_out += 1


def _name_company(conn: sqlite3.Connection, rules: RuleSet, job: Job, report: SourceReport) -> None:
    """A known job stored as "(Indeed)" that now comes with its company and place is screened
    again: the place may be outside the area, or the company's own site may list the same
    opening. Then the alert copy is the duplicate, and the one from the company stays."""
    if is_placeholder(job.company):
        return
    key = dedupe_key(job)
    if (job_id := db.name_company(conn, job, key)) is None:
        return
    result = rules.evaluate(job)
    if result.ok and (original := db.find_by_dedupe_key(conn, key, other_than=job_id)):
        result = RuleResult(False, f"duplicate_of: {original}", result.role_family)
    if not result.ok:
        db.set_status(conn, job_id, Status.SKIPPED, result.reason, result.role_family)
        report.screened_out += 1


# What an HTTP error means, said plainly (the report, the panel and the daily log show it)
_STATUS_TEXT = {
    401: "Acceso negado: el sitio pide iniciar sesión para esa consulta.",
    403: (
        "Acceso negado: el sitio rechazó la consulta. Puede que bloquee programas automáticos o "
        "que esa página ya no sea pública."
    ),
    404: (
        "Dirección no encontrada: la página de empleos ya no está en esa URL. Lo más probable es "
        "que la empresa cambió su sitio; revisa esa fuente en targets.yaml."
    ),
    429: (
        "Demasiadas consultas: el sitio pidió bajar el ritmo y siguió negándose después de "
        "reintentar. Vuelve a probar en la próxima corrida."
    ),
}
_STATUS_TEXT[410] = _STATUS_TEXT[404]
_SERVER_ERROR = (
    "Falla del sitio: su servidor tuvo un error propio y no se recuperó después de reintentar. "
    "Suele resolverse solo."
)
_CHALLENGE = (
    ANTI_BOT + ": {who} pidió una verificación de navegador («Security Check») en vez de "
    "responder. No es una falla de JobBot ni un cambio en la página: el sitio frena las "
    "consultas automáticas. JobBot no se salta esas verificaciones (ADR-003) ni reintenta: "
)
_CHALLENGE_NEXT = "vuelve a probar en la próxima corrida."
# A platform's bot check stops all its sources (ADR-032).
_CHALLENGE_PLATFORM = "deja de consultar todo {name} en esta corrida (ADR-032)."
_CHALLENGE_DAILY = "deja de consultar todo {name} y vuelve a probar mañana (ADR-032)."


def _host(exc: httpx.HTTPError) -> str:
    try:
        return exc.request.url.host
    except RuntimeError:  # an error built without its request
        return ""


def describe_error(exc: Exception, source: Source | None = None) -> str:
    """Plain words first, then the technical detail in brackets: code and site, never the
    whole URL. `source`: who failed, which tells whether a bot check stops its platform."""
    if isinstance(exc, ChallengeError):
        who = "Cloudflare, la protección del sitio," if exc.by_cloudflare else "el sitio"
        then = _CHALLENGE_NEXT
        if source is not None and source.platform:
            then = (_CHALLENGE_DAILY if source.once_a_day else _CHALLENGE_PLATFORM).format(
                name=source.platform.capitalize()
            )
        detail = f"[HTTP {exc.response.status_code} · {exc.response.url.host}]"
        return f"{_CHALLENGE.format(who=who)}{then} {detail}"
    if isinstance(exc, NotJsonError):
        return f"Sin datos: {exc}"
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        text = _STATUS_TEXT.get(code) or (
            _SERVER_ERROR if code >= 500 else f"El sitio rechazó la consulta (HTTP {code})."
        )
        if detail := error_detail(exc.response):
            text += f" Motivo que dio el sitio: {detail}."
        return f"{text} [HTTP {code} · {_host(exc)}]"
    if isinstance(exc, httpx.TimeoutException):
        text = "Sin respuesta: el sitio tardó demasiado en contestar. Suele ser pasajero."
    elif isinstance(exc, httpx.ConnectError):
        text = (
            "Sin conexión: no se pudo llegar al sitio (sin internet en ese momento o el sitio "
            "caído). Vuelve a probar en la próxima corrida."
        )
    elif isinstance(exc, httpx.HTTPError):
        text = "La conexión con el sitio se cortó a mitad de la consulta."
    else:
        text = "La respuesta del sitio cambió de forma y JobBot no la entendió: hay que ajustarlo."
    where = _host(exc) if isinstance(exc, httpx.HTTPError) else ""
    return f"{text} [{type(exc).__name__}: {exc}{f' · {where}' if where else ''}]"


def _record_applications(source: ConfirmationSource, conn: sqlite3.Connection) -> SourceReport:
    report = SourceReport()
    try:
        report.confirmations, marked = source.record(conn)
        report.marked_applied = len(marked)
    except SourceNotConfigured as exc:
        report.not_configured = str(exc)
    except Exception as exc:  # like any other source: reported, the run goes on
        report.error = describe_error(exc)
    return report


def _record_replies(source: ReplySource, conn: sqlite3.Connection) -> SourceReport:
    report = SourceReport()
    try:
        report.replies, report.closed_by_reply, report.asked = source.record(conn)
    except SourceNotConfigured as exc:
        report.not_configured = str(exc)
    except Exception as exc:
        report.error = describe_error(exc)
    return report


def platform_of(source: Source) -> str:
    return source.platform or source.name


def _queried_recently(conn: sqlite3.Connection, source: Source) -> str:
    """Why the source's platform is not due yet ("5.2 h < 6 h"), or "" when it is."""
    last = db.last_query(conn, platform_of(source))
    if source.once_a_day:
        if last and last.astimezone().date() == datetime.now().astimezone().date():
            return f"hoy a las {last.astimezone():%H:%M}; una vez al día"
        return ""
    if not source.min_hours_between_runs:
        return ""
    # Runs before ADR-032 left only the jobs' last_seen_at.
    known = [last, db.last_seen_at(conn, source.name)]
    if not (times := [t for t in known if t]):
        return ""
    hours = (datetime.now(UTC) - max(times)).total_seconds() / 3600
    if hours >= source.min_hours_between_runs:
        return ""
    return f"{hours:.1f} h < {source.min_hours_between_runs:g} h"


def run_sources(
    sources: Iterable[Source], conn: sqlite3.Connection, rules: RuleSet
) -> Iterator[tuple[Source, SourceReport]]:
    """Each source in turn, by platform (ADR-032): whether a platform is due is decided at its
    first source, and a bot check stops the rest of the platform for the run. One search at a
    time: another one, in this process or another, is waited for (ADR-035)."""
    skips: dict[str, dict[str, str]] = {}  # platform -> why its sources are skipped ({} = run)
    with runlock.exclusive(db.lock_path(conn)):
        for source in sources:
            platform = platform_of(source)
            if platform not in skips:
                wait = _queried_recently(conn, source)
                skips[platform] = {"skipped_recent": wait} if wait else {}
            if skips[platform]:
                yield source, SourceReport(**skips[platform])
                continue
            started = db.utc_now()
            report = run_source(source, conn, rules)
            if report.blocked or not report.error:
                db.record_query(conn, platform, started)
            if report.blocked and source.platform:
                skips[platform] = {"skipped_blocked": source.name}
            yield source, report


def run_source(source: Source, conn: sqlite3.Connection, rules: RuleSet) -> SourceReport:
    """One source, now: `run_sources` decides which ones are due."""
    if isinstance(source, ConfirmationSource):
        return _record_applications(source, conn)
    if isinstance(source, ReplySource):
        return _record_replies(source, conn)
    report = SourceReport()
    started = db.utc_now()
    try:
        for job in source.fetch():
            if db.touch_seen(conn, job.ats, job.ats_job_id):
                report.seen += 1
                db.note_posting(conn, job)
                _complete_details(source, conn, rules, job, report)
                _name_company(conn, rules, job, report)
                continue

            result = rules.evaluate(job)
            if result.ok and not job.description:
                # Details cost one request per job: only for postings that already passed.
                with contextlib.suppress(*FETCH_ERRORS):
                    job = source.enrich(job)
                result = rules.evaluate(job)

            key = dedupe_key(job)
            status, reason = Status.DISCOVERED, result.reason
            if not result.ok:
                status, reason = Status.SKIPPED, result.reason
            elif (original := db.find_by_dedupe_key(conn, key)) is not None or (
                original := same_opening_elsewhere(conn, rules, job)
            ) is not None:
                status, reason = Status.SKIPPED, f"duplicate_of: {original}"

            db.insert_job(
                conn,
                job,
                dedupe_key=key,
                status=status,
                status_reason=reason,
                role_family=result.role_family,
            )
            if status is Status.DISCOVERED:
                report.new_matched += 1
            else:
                report.new_skipped += 1
                report.skip_reasons[reason.split(":")[0]] += 1
        if source.listing_complete:  # every open posting was seen: the missing ones closed
            db.record_listing(conn, source.name, started)
    except SourceNotConfigured as exc:
        report.not_configured = str(exc)
    except Exception as exc:
        # FETCH_ERRORS, or a response shaped unlike any seen before: one site's failure is
        # reported and the others still run.
        report.error = describe_error(exc, source)
        report.blocked = isinstance(exc, ChallengeError)
    return report
