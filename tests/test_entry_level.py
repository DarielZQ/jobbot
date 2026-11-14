"""First jobs (ADR-024): the panel's "Entrada" chip, the enrollment note and LinkedIn searches
by experience level."""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest

from conftest import make_job
from jobbot import daily
from jobbot.config import LinkedInSearches, Targets, load_search_rules
from jobbot.core import db
from jobbot.core.state import Status
from jobbot.matching.rules import ENROLLMENT_REQUIRED, entry_level
from jobbot.panel import list_view

HEREDIA = "Heredia, Costa Rica"


@pytest.mark.parametrize(
    "title",
    [
        "IT Support Intern",
        "Internship - Cloud Operations",
        "Trainee Soporte TI",
        "Junior Python Developer",
        "Jr. QA Automation Tester",
        "Entry-Level Data Analyst",
        "Graduate Program - Technology Analyst",
        "Practicante de Sistemas",
        "Pasantía en Desarrollo de Software",
        "Early Career IT Specialist",
    ],
)
def test_first_job_titles_are_entry_level(title: str) -> None:
    assert entry_level(title)


@pytest.mark.parametrize(
    "title",
    [
        "Internal Audit Analyst",
        "International Support Specialist",
        "Service Desk Analyst L1",
        "IT Support Analyst",
    ],
)
def test_other_titles_are_not_entry_level(title: str) -> None:
    assert not entry_level(title)


@pytest.mark.parametrize(
    "description",
    [
        "Requirements: must be currently enrolled in a Bachelor's degree in Computer Science.",
        "Candidates must be enrolled in a degree program with graduation in 2027.",
        "Requisito: ser estudiante activo de Ingeniería en Sistemas.",
        "Estar cursando la carrera de Informática (mínimo 50% de avance).",
    ],
)
def test_a_posting_that_asks_for_enrollment_passes_with_a_note(rules, description: str) -> None:
    result = rules.evaluate(
        make_job(title="IT Support Intern", location=HEREDIA, description=description)
    )

    assert result.ok
    assert result.reason.startswith(ENROLLMENT_REQUIRED)


def test_a_posting_open_to_recent_graduates_has_no_enrollment_note(rules) -> None:
    result = rules.evaluate(
        make_job(
            title="IT Support Intern",
            location=HEREDIA,
            description="Open to current students and recent graduates.",
        )
    )

    assert result.ok and result.reason == ""


def test_the_enrollment_note_is_shown_in_plain_words() -> None:
    row = db.JobRow(
        id=1,
        source="s",
        company="Acme",
        title="IT Support Intern",
        location=HEREDIA,
        url="u",
        status=Status.DISCOVERED,
        status_reason=f"{ENROLLMENT_REQUIRED}: currently enrolled",
        role_family="it_support",
        first_seen_at=datetime.now(UTC).isoformat(),
    )

    assert daily.job_notes(row) == ["Pide estar matriculado: revisa si aceptan egresados"]


def test_the_panel_marks_entry_level_jobs(conn) -> None:
    for number, title in enumerate(["IT Support Intern", "IT Support Analyst"]):
        db.insert_job(
            conn,
            make_job(ats_job_id=str(number), title=title, location=HEREDIA),
            dedupe_key=str(number),
            status=Status.DISCOVERED,
            status_reason="",
            role_family="it_support",
        )

    jobs = {job["title"]: job for job in list_view(conn, "pending")}

    assert jobs["IT Support Intern"]["entry"] is True
    assert jobs["IT Support Analyst"]["entry"] is False


def test_linkedin_searches_can_filter_by_level_over_their_own_window() -> None:
    targets = Targets(
        linkedin_searches=[
            LinkedInSearches(
                label="Primer empleo · Costa Rica",
                keywords=["trainee"],
                geo_id="101739942",
                location="Costa Rica",
                experience=["internship", "entry"],
                hours=168,
            ),
            LinkedInSearches(label="Costa Rica", keywords=["help desk"], location="Costa Rica"),
        ]
    )

    first, second = daily.linkedin_links(targets, load_search_rules())
    query = parse_qs(urlparse(first.links[0][1]).query)

    assert first.label == "Primer empleo · Costa Rica" and first.hours == 168
    assert query["f_E"] == ["1,2"] and query["f_TPR"] == ["r604800"]
    # A group without its own window keeps `fresh_hours` and no level filter
    assert second.hours == 24
    assert "f_E" not in parse_qs(urlparse(second.links[0][1]).query)


def test_window_text_reads_hours_and_whole_days() -> None:
    assert daily.window_text(24) == "últimas 24 h"
    assert daily.window_text(168) == "últimos 7 días"
    assert daily.window_text(36) == "últimas 36 h"
