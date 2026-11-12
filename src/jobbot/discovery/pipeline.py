"""Discovery run: fetch -> filter -> dedupe -> persist."""

from __future__ import annotations

import contextlib
import sqlite3
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from jobbot.config import Targets, resolve
from jobbot.core import db
from jobbot.core.http import HttpClient, error_detail
from jobbot.core.models import Job
from jobbot.core.state import Status
from jobbot.discovery.amazon import AmazonSource
from jobbot.discovery.applications import ConfirmationSource
from jobbot.discovery.ashby import AshbySource
from jobbot.discovery.base import Source, SourceNotConfigured
from jobbot.discovery.deel import DeelSource
from jobbot.discovery.elempleo import ElempleoSource
from jobbot.discovery.email_alerts import PARSERS, EmailAlertSource
from jobbot.discovery.getonboard import GetOnBoardSource
from jobbot.discovery.greenhouse import GreenhouseSource
from jobbot.discovery.himalayas import HimalayasSource
from jobbot.discovery.icims import ICimsSource
from jobbot.discovery.jibe import JibeSource
from jobbot.discovery.jobicy import JobicySource
from jobbot.discovery.lever import LeverSource
from jobbot.discovery.recruitee import RecruiteeSource
from jobbot.discovery.remotive import RemotiveSource
from jobbot.discovery.successfactors import SuccessFactorsSource
from jobbot.discovery.workday import WorkdaySource
from jobbot.mail.gmail import GmailClient, access_token
from jobbot.matching.dedupe import dedupe_key
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
    skipped_recent: str = ""
    not_configured: str = ""
    # Open jobs reopened by rescreen that failed the filters once their details arrived.
    screened_out: int = 0
    # ConfirmationSource only: confirmation emails read and jobs marked (or added) as applied.
    confirmations: int | None = None
    marked_applied: int = 0


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
    return sources


def rescreen(conn: sqlite3.Connection, rules: RuleSet) -> Counter[str]:
    """Re-apply the current filters to stored jobs, without touching the network.

    Postings whose details were never fetched (skipped before enrichment) are judged on
    title and location only.
    """
    changes: Counter[str] = Counter()
    for job_id, status, reason, job, seen_at in db.screenable_jobs(conn):
        result = rules.evaluate(job, seen_at)
        if result.ok and rules.too_old(job.posted_at, seen_at):  # undated: since first seen
            days = rules.age_days(job.posted_at, seen_at)
            result = RuleResult(False, f"{TOO_OLD}: {days} días", result.role_family)
        if result.ok and status is Status.SKIPPED:
            key = dedupe_key(job)
            original = db.find_by_dedupe_key(conn, key)
            if original is None:
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


def _describe(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    if isinstance(exc, httpx.HTTPStatusError) and (detail := error_detail(exc.response)):
        text += f" ({detail})"
    return text


def _record_applications(source: ConfirmationSource, conn: sqlite3.Connection) -> SourceReport:
    report = SourceReport()
    try:
        report.confirmations, marked = source.record(conn)
        report.marked_applied = len(marked)
    except SourceNotConfigured as exc:
        report.not_configured = str(exc)
    except Exception as exc:  # like any other source: reported, the run goes on
        report.error = _describe(exc)
    return report


def run_source(source: Source, conn: sqlite3.Connection, rules: RuleSet) -> SourceReport:
    if isinstance(source, ConfirmationSource):
        return _record_applications(source, conn)
    report = SourceReport()
    if source.min_hours_between_runs and (last := db.last_seen_at(conn, source.name)):
        hours = (datetime.now(UTC) - last).total_seconds() / 3600
        if hours < source.min_hours_between_runs:
            report.skipped_recent = f"{hours:.1f} h < {source.min_hours_between_runs:g} h"
            return report
    try:
        for job in source.fetch():
            if db.touch_seen(conn, job.ats, job.ats_job_id):
                report.seen += 1
                db.note_posting(conn, job)
                _complete_details(source, conn, rules, job, report)
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
            elif (original := db.find_by_dedupe_key(conn, key)) is not None:
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
    except SourceNotConfigured as exc:
        report.not_configured = str(exc)
    except Exception as exc:
        # FETCH_ERRORS, or a response shaped unlike any seen before: one site's failure is
        # reported and the others still run.
        report.error = _describe(exc)
    return report
