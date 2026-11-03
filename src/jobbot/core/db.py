"""SQLite persistence (ADR-002): schema migrations via PRAGMA user_version."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from jobbot.core.models import Job
from jobbot.core.state import InvalidTransition, Status, check_transition

MIGRATIONS: list[str] = [
    """
    CREATE TABLE jobs (
        id            INTEGER PRIMARY KEY,
        source        TEXT NOT NULL,
        ats           TEXT NOT NULL,
        ats_job_id    TEXT NOT NULL,
        company       TEXT NOT NULL,
        title         TEXT NOT NULL,
        location      TEXT NOT NULL DEFAULT '',
        url           TEXT NOT NULL,
        remote        INTEGER NOT NULL DEFAULT 0,
        posted_at     TEXT,
        description   TEXT NOT NULL DEFAULT '',
        dedupe_key    TEXT NOT NULL,
        status        TEXT NOT NULL,
        status_reason TEXT NOT NULL DEFAULT '',
        first_seen_at TEXT NOT NULL,
        last_seen_at  TEXT NOT NULL,
        updated_at    TEXT NOT NULL,
        UNIQUE (ats, ats_job_id)
    );
    CREATE INDEX idx_jobs_dedupe ON jobs (dedupe_key);
    CREATE INDEX idx_jobs_status ON jobs (status);
    """,
    # ADR-009: role families
    "ALTER TABLE jobs ADD COLUMN role_family TEXT NOT NULL DEFAULT '';",
    # ADR-019: grill-me decisions queued by the daily run, and each source's run history
    """
    CREATE TABLE decisions (
        id          INTEGER PRIMARY KEY,
        key         TEXT NOT NULL UNIQUE,
        kind        TEXT NOT NULL,
        question    TEXT NOT NULL,
        options     TEXT NOT NULL,
        recommended TEXT NOT NULL DEFAULT '',
        reason      TEXT NOT NULL DEFAULT '',
        status      TEXT NOT NULL DEFAULT 'pending',
        answer      TEXT NOT NULL DEFAULT '',
        created_at  TEXT NOT NULL,
        answered_at TEXT
    );
    CREATE TABLE source_runs (
        id     INTEGER PRIMARY KEY,
        source TEXT NOT NULL,
        ran_at TEXT NOT NULL,
        error  TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX idx_source_runs ON source_runs (source, ran_at);
    """,
]


@dataclass(frozen=True)
class JobRow:
    id: int
    source: str
    company: str
    title: str
    location: str
    url: str
    status: Status
    status_reason: str
    role_family: str
    first_seen_at: str
    updated_at: str = ""
    remote: bool = False  # 100 % remote; hybrid jobs are False


_ROW_COLUMNS = (
    "id, source, company, title, location, url, status, status_reason, role_family, "
    "first_seen_at, updated_at, remote"
)
# Reasons set by the candidate (`jobbot applied`, panel): `rescreen` never overrides them.
APPLIED_MANUALLY = "applied_manually"
NOT_INTERESTED = "not_interested"
REOPENED_MANUALLY = "reopened_manually"
# Set by the bot from a site's confirmation email (ADR-018); the candidate can undo it.
APPLIED_BY_EMAIL = "applied_by_email"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _job_row(row: sqlite3.Row) -> JobRow:
    return JobRow(**{**dict(row), "status": Status(row["status"]), "remote": bool(row["remote"])})


utc_now = _now


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for index, script in enumerate(MIGRATIONS[version:], start=version + 1):
        with conn:
            conn.executescript(script)
            conn.execute(f"PRAGMA user_version = {index}")


def touch_seen(conn: sqlite3.Connection, ats: str, ats_job_id: str) -> bool:
    """Refresh last_seen_at of a known job. Returns False if the job is new.

    The status of a known job is never touched: a job already queued or applied
    must not be reset by a later discovery run.
    """
    with conn:
        updated = conn.execute(
            "UPDATE jobs SET last_seen_at = ? WHERE ats = ? AND ats_job_id = ?",
            (_now(), ats, ats_job_id),
        ).rowcount
    return bool(updated)


def open_without_details(conn: sqlite3.Connection, ats: str, ats_job_id: str) -> int | None:
    """Id of a known open job whose details were never fetched (reopened offline by rescreen).

    Jobs the candidate reopened by hand are left out: their decision stands.
    """
    row = conn.execute(
        "SELECT id FROM jobs WHERE ats = ? AND ats_job_id = ? AND status = ? "
        "AND COALESCE(description, '') = '' AND COALESCE(status_reason, '') != ?",
        (ats, ats_job_id, Status.DISCOVERED.value, REOPENED_MANUALLY),
    ).fetchone()
    return row["id"] if row else None


def set_description(conn: sqlite3.Connection, job_id: int, description: str) -> None:
    with conn:
        conn.execute(
            "UPDATE jobs SET description = ?, updated_at = ? WHERE id = ?",
            (description, _now(), job_id),
        )


def insert_job(
    conn: sqlite3.Connection,
    job: Job,
    *,
    dedupe_key: str,
    status: Status,
    status_reason: str = "",
    role_family: str = "",
) -> int:
    now = _now()
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO jobs (source, ats, ats_job_id, company, title, location, url, remote,
                              posted_at, description, dedupe_key, status, status_reason,
                              role_family, first_seen_at, last_seen_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.source,
                job.ats,
                job.ats_job_id,
                job.company,
                job.title,
                job.location,
                job.url,
                int(job.remote),
                job.posted_at.isoformat() if job.posted_at else None,
                job.description,
                dedupe_key,
                status.value,
                status_reason,
                role_family,
                now,
                now,
                now,
            ),
        )
    return int(cursor.lastrowid)


def last_seen_at(conn: sqlite3.Connection, source: str) -> datetime | None:
    """Most recent time any job from this source was seen (≈ its last successful run)."""
    row = conn.execute("SELECT MAX(last_seen_at) AS ts FROM jobs WHERE source = ?", (source,))
    value = row.fetchone()["ts"]
    return datetime.fromisoformat(value) if value else None


def find_by_dedupe_key(conn: sqlite3.Connection, dedupe_key: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM jobs WHERE dedupe_key = ? AND status != ? ORDER BY id LIMIT 1",
        (dedupe_key, Status.SKIPPED.value),
    ).fetchone()
    return row["id"] if row else None


def set_status(
    conn: sqlite3.Connection,
    job_id: int,
    new: Status,
    reason: str = "",
    role_family: str | None = None,
) -> None:
    row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise KeyError(job_id)
    check_transition(Status(row["status"]), new)
    with conn:
        conn.execute(
            "UPDATE jobs SET status = ?, status_reason = ?, "
            "role_family = COALESCE(?, role_family), updated_at = ? WHERE id = ?",
            (new.value, reason, role_family, _now(), job_id),
        )


def screenable_jobs(conn: sqlite3.Connection) -> list[tuple[int, Status, str, Job]]:
    """Jobs whose screening can be redone: discovered, or skipped by a filter.

    Duplicates and the candidate's own decisions (not interested, reopened) are left alone.
    """
    rows = conn.execute(
        "SELECT * FROM jobs WHERE (status = ? OR (status = ? AND status_reason NOT LIKE ?)) "
        "AND status_reason NOT IN (?, ?)",
        (
            Status.DISCOVERED.value,
            Status.SKIPPED.value,
            "duplicate_of%",
            NOT_INTERESTED,
            REOPENED_MANUALLY,
        ),
    ).fetchall()
    return [
        (
            r["id"],
            Status(r["status"]),
            r["status_reason"],
            Job(
                source=r["source"],
                ats=r["ats"],
                ats_job_id=r["ats_job_id"],
                company=r["company"],
                title=r["title"],
                location=r["location"],
                url=r["url"],
                remote=bool(r["remote"]),
                description=r["description"],
            ),
        )
        for r in rows
    ]


def list_jobs(
    conn: sqlite3.Connection,
    *,
    status: Status | None = None,
    role_family: str | None = None,
    limit: int = 100,
) -> list[JobRow]:
    query = f"SELECT {_ROW_COLUMNS} FROM jobs"
    conditions: list[str] = []
    params: list[object] = []
    if status is not None:
        conditions.append("status = ?")
        params.append(status.value)
    if role_family is not None:
        conditions.append("role_family = ?")
        params.append(role_family)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY first_seen_at DESC, id DESC LIMIT ?"
    rows = conn.execute(query, (*params, limit)).fetchall()
    return [_job_row(r) for r in rows]


def applied_jobs(conn: sqlite3.Connection) -> list[JobRow]:
    """Every job the candidate applied to, whatever happened next."""
    statuses = (
        Status.SUBMITTED,
        Status.CONFIRMED,
        Status.UNCERTAIN,
        Status.INTERVIEW,
        Status.REJECTED,
    )
    return [r for s in statuses for r in list_jobs(conn, status=s, limit=100_000)]


def find_job(conn: sqlite3.Connection, ats: str, ats_job_id: str) -> JobRow | None:
    row = conn.execute(
        f"SELECT {_ROW_COLUMNS} FROM jobs WHERE ats = ? AND ats_job_id = ?", (ats, ats_job_id)
    ).fetchone()
    return _job_row(row) if row else None


def get_job(conn: sqlite3.Connection, job_id: int) -> JobRow | None:
    row = conn.execute(f"SELECT {_ROW_COLUMNS} FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _job_row(row) if row else None


def descriptions(conn: sqlite3.Connection, job_ids: Iterable[int]) -> dict[int, str]:
    ids = list(job_ids)
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = conn.execute(f"SELECT id, description FROM jobs WHERE id IN ({marks})", ids)
    return {r["id"]: r["description"] for r in rows}


def mark_applied(conn: sqlite3.Connection, job_id: int, *, undo: bool = False) -> JobRow:
    """The candidate applied by hand (`jobbot applied`); `undo` reopens only a mark made by hand
    or from a confirmation email. An undone email mark is not redone by the next run."""
    job = get_job(conn, job_id)
    if job is None:
        raise KeyError(job_id)
    if undo:
        marks = (APPLIED_MANUALLY, APPLIED_BY_EMAIL)
        if job.status != Status.SUBMITTED or job.status_reason not in marks:
            raise InvalidTransition(f"#{job_id} was not marked as applied by hand or by email")
        reason = REOPENED_MANUALLY if job.status_reason == APPLIED_BY_EMAIL else ""
        set_status(conn, job_id, Status.DISCOVERED, reason)
    else:
        set_status(conn, job_id, Status.SUBMITTED, APPLIED_MANUALLY)
    return get_job(conn, job_id)


def mark_not_interested(conn: sqlite3.Connection, job_id: int) -> JobRow:
    """The candidate discards an open job; `rescreen` will not reopen it."""
    set_status(conn, job_id, Status.SKIPPED, NOT_INTERESTED)
    return get_job(conn, job_id)


def reopen(conn: sqlite3.Connection, job_id: int) -> JobRow:
    """Back to pending: a job the candidate or a filter discarded (never a duplicate)."""
    job = get_job(conn, job_id)
    if job is None:
        raise KeyError(job_id)
    if job.status != Status.SKIPPED or job.status_reason.startswith("duplicate_of"):
        raise InvalidTransition(f"#{job_id} cannot be reopened ({job.status.value})")
    set_status(conn, job_id, Status.DISCOVERED, REOPENED_MANUALLY)
    return get_job(conn, job_id)


def set_outcome(conn: sqlite3.Connection, job_id: int, outcome: Status) -> JobRow:
    """What happened after applying: INTERVIEW or REJECTED, marked by the candidate."""
    if outcome not in (Status.INTERVIEW, Status.REJECTED):
        raise ValueError(outcome)
    set_status(conn, job_id, outcome, "manual")
    job = get_job(conn, job_id)
    if job is None:
        raise KeyError(job_id)
    return job


def count_by_status(conn: sqlite3.Connection) -> dict[Status, int]:
    rows = conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status").fetchall()
    return {Status(r["status"]): r["n"] for r in rows}


def last_search_at(conn: sqlite3.Connection) -> datetime | None:
    """When any source last returned jobs (≈ the last discovery run)."""
    value = conn.execute("SELECT MAX(last_seen_at) AS ts FROM jobs").fetchone()["ts"]
    return datetime.fromisoformat(value) if value else None


def new_matches_since(conn: sqlite3.Connection, since: str) -> list[JobRow]:
    """Jobs first seen at or after `since` (UTC ISO) that passed the filters."""
    rows = conn.execute(
        f"SELECT {_ROW_COLUMNS} FROM jobs WHERE status = ? AND first_seen_at >= ? "
        "ORDER BY role_family, company, title",
        (Status.DISCOVERED.value, since),
    ).fetchall()
    return [_job_row(r) for r in rows]


def stats(conn: sqlite3.Connection) -> list[tuple[str, str, str, int]]:
    rows = conn.execute(
        "SELECT source, role_family, status, COUNT(*) AS n FROM jobs "
        "GROUP BY source, role_family, status ORDER BY source, role_family, status"
    ).fetchall()
    return [(r["source"], r["role_family"], r["status"], r["n"]) for r in rows]
