"""Grill-me in the background: after each daily run, questions from what the data shows.

Three detectors, at most `MAX_NEW_PER_DAY` new questions a day so they never pile up:
- an application with no news for `STALE_DAYS`: close it as "sin respuesta"?
- a source that failed its last `FAILING_RUNS` runs: disable it?
- a skill asked by many open postings that the profile never mentions: do you have it?

A question is identified by its `key`, so the same one is never asked twice. Answering applies
the option the user picked (its text says what it does); nothing else changes behind their back.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import yaml

from jobbot import paths
from jobbot.core import db
from jobbot.core.state import Status
from jobbot.grill import GRILL_DIR
from jobbot.grill.apply import FACTS, SETTINGS, Plan
from jobbot.matching.normalize import normalize_text

MAX_NEW_PER_DAY = 3
STALE_DAYS = 21
FAILING_RUNS = 3
SKILL_SHARE = 0.3
SKILL_MIN_JOBS = 5

CLOSE, WAIT = "Sí, cerrarla", "Esperar más"
DISABLE, KEEP = "Desactivarla", "Seguir intentando"
AT_WORK, LEARNING, NO = "Sí, la he usado en el trabajo", "La estoy aprendiendo", "No"


@dataclass(frozen=True)
class Decision:
    id: int
    key: str
    kind: str
    question: str
    options: tuple[str, ...]
    recommended: str
    reason: str


def record_runs(conn: sqlite3.Connection, results: Sequence[tuple[str, object]]) -> None:
    """One row per source that actually ran (skipped and unconfigured ones do not count)."""
    now = db.utc_now()
    rows = [
        (name, now, report.error)
        for name, report in results
        if not (report.skipped_recent or report.not_configured)
    ]
    with conn:
        conn.executemany("INSERT INTO source_runs (source, ran_at, error) VALUES (?, ?, ?)", rows)


def _stale(conn: sqlite3.Connection, now: datetime) -> list[dict]:
    limit = (now - timedelta(days=STALE_DAYS)).isoformat(timespec="seconds")
    return [
        {
            "key": f"stale:{job.id}",
            "kind": "stale",
            "question": (
                f"Postulaste a «{job.title}» ({job.company}) hace más de {STALE_DAYS // 7} "
                "semanas y no hubo novedades. ¿La cierro como sin respuesta?"
            ),
            "options": [CLOSE, WAIT],
            "recommended": CLOSE,
            "reason": "Si después te llaman, la pasas a Entrevistas desde Cerradas.",
        }
        for status in (Status.SUBMITTED, Status.CONFIRMED)
        for job in db.list_jobs(conn, status=status, limit=100_000)
        if job.updated_at and job.updated_at < limit
    ]


def _failing(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT source, error FROM source_runs ORDER BY ran_at DESC, id DESC")
    recent: dict[str, list[str]] = {}
    for row in rows:
        recent.setdefault(row["source"], []).append(row["error"])
    return [
        {
            "key": f"failing:{source}",
            "kind": "failing",
            "question": (
                f"La fuente {source} falló en sus últimas {FAILING_RUNS} búsquedas "
                f"({errors[0][:120]}). ¿La desactivo?"
            ),
            "options": [DISABLE, KEEP],
            "recommended": DISABLE,
            "reason": (
                "Varios fallos seguidos suelen ser un cambio del sitio. Para reactivarla, quítala "
                "de disabled_sources en config/settings.yaml."
            ),
        }
        for source, errors in recent.items()
        if len(errors) >= FAILING_RUNS and all(errors[:FAILING_RUNS])
    ]


def _profile_text() -> str:
    files = [paths.profile_dir() / "facts.yaml", *paths.resumes_dir().glob("*.yaml")]
    return normalize_text(" ".join(f.read_text(encoding="utf-8") for f in files if f.exists()))


def _skill_gaps(conn: sqlite3.Connection) -> list[dict]:
    skills = yaml.safe_load((GRILL_DIR / "skills.yaml").read_text(encoding="utf-8"))
    open_jobs = db.list_jobs(conn, status=Status.DISCOVERED, limit=100_000)
    descriptions = db.descriptions(conn, [j.id for j in open_jobs])
    # Only postings with a description: a bare title says too little about required skills.
    texts = [
        normalize_text(f"{job.title} {descriptions[job.id]}")
        for job in open_jobs
        if descriptions.get(job.id)
    ]
    profile = _profile_text()
    gaps = []
    for name, pattern in skills.items():
        regex = re.compile(pattern, re.I)
        if regex.search(profile):
            continue
        asked = sum(1 for text in texts if regex.search(text))
        if asked >= SKILL_MIN_JOBS and asked >= SKILL_SHARE * len(texts):
            gaps.append(
                {
                    "key": f"skill:{name}",
                    "kind": "skill",
                    "question": (
                        f"{asked} de tus {len(texts)} vacantes pendientes piden {name} y tu "
                        "perfil no lo menciona. ¿Lo has usado?"
                    ),
                    # A fact about the user: no recommended answer.
                    "options": [AT_WORK, LEARNING, NO],
                    "recommended": "",
                    "reason": "",
                }
            )
    return gaps


def refresh(conn: sqlite3.Connection, now: datetime | None = None) -> int:
    """Queue new questions (never repeated, at most MAX_NEW_PER_DAY a day). Returns how many."""
    now = now or datetime.now(UTC)
    today = now.date().isoformat()
    queued_today = conn.execute(
        "SELECT COUNT(*) FROM decisions WHERE substr(created_at, 1, 10) = ?", (today,)
    ).fetchone()[0]
    room = MAX_NEW_PER_DAY - queued_today
    known = {row["key"] for row in conn.execute("SELECT key FROM decisions")}
    proposals = [*_failing(conn), *_stale(conn, now), *_skill_gaps(conn)]
    new = [p for p in proposals if p["key"] not in known]
    with conn:
        for proposal in new[: max(room, 0)]:
            conn.execute(
                "INSERT INTO decisions (key, kind, question, options, recommended, reason, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    proposal["key"],
                    proposal["kind"],
                    proposal["question"],
                    json.dumps(proposal["options"], ensure_ascii=False),
                    proposal["recommended"],
                    proposal["reason"],
                    now.isoformat(timespec="seconds"),
                ),
            )
    return min(len(new), max(room, 0))


def pending(conn: sqlite3.Connection) -> list[Decision]:
    rows = conn.execute("SELECT * FROM decisions WHERE status = 'pending' ORDER BY id")
    return [
        Decision(
            row["id"],
            row["key"],
            row["kind"],
            row["question"],
            tuple(json.loads(row["options"])),
            row["recommended"],
            row["reason"],
        )
        for row in rows
    ]


def answer(conn: sqlite3.Connection, decision_id: int, option: str) -> str:
    """Apply the chosen option. Raises KeyError (no such pending decision) or ValueError."""
    decision = next((d for d in pending(conn) if d.id == decision_id), None)
    if decision is None:
        raise KeyError(decision_id)
    if option not in decision.options:
        raise ValueError(option)
    subject = decision.key.split(":", 1)[1]
    done = "Anotado."
    if decision.kind == "stale" and option == CLOSE:
        db.set_outcome(conn, int(subject), Status.REJECTED)
        done = "Vacante cerrada como sin respuesta."
    elif decision.kind == "failing" and option == DISABLE:
        plan = Plan()
        plan.edit_list(SETTINGS, ("disabled_sources",), lambda items: [*items, subject])
        plan.save()
        done = f"{subject} desactivada (config/settings.yaml: disabled_sources)."
    elif decision.kind == "skill" and option in (AT_WORK, LEARNING):
        group = "work" if option == AT_WORK else "self_study"
        plan = Plan()
        plan.edit_list(FACTS, ("skills", group), lambda items: [*items, subject])
        plan.save()
        done = f"{subject} agregado a profile/facts.yaml (skills.{group})."
    with conn:
        conn.execute(
            "UPDATE decisions SET status = 'answered', answer = ?, answered_at = ? WHERE id = ?",
            (option, db.utc_now(), decision_id),
        )
    return done
