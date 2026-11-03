"""Which CV to send per job (ADR-015) and marking jobs the candidate applied to by hand."""

from __future__ import annotations

import pytest

from conftest import make_job
from jobbot.config import load_search_rules
from jobbot.core import db
from jobbot.core.state import InvalidTransition, Status
from jobbot.matching.language import detect_language, recommend_resume


@pytest.mark.parametrize(
    ("title", "description", "lang"),
    [
        ("Auxiliar de soporte técnico", "", "es"),
        ("Técnico Soporte Core N1", "", "es"),
        ("Support Engineer I, AWS", "", "en"),
        ("Junior Networking Agent", "", "en"),  # no clue either way: English
        (
            "Application Support Analyst – SQL",
            "Buscamos analista con experiencia en soporte de aplicaciones y conocimientos "
            "de SQL para la empresa. Requisitos: inglés intermedio.",
            "es",  # Spanish body beats an English title
        ),
        (
            "Analista de Soporte",
            "You will join our team to provide support to customers. Requirements: "
            "experience with Windows and Active Directory, english B2, and the will to learn.",
            "en",
        ),
    ],
)
def test_detect_language(title: str, description: str, lang: str) -> None:
    assert detect_language(title, description) == lang


def test_recommend_resume_uses_family_cv_and_posting_language() -> None:
    rules = load_search_rules()  # real config/search.yaml

    it = recommend_resume(rules, "it_support", "Soporte técnico")
    data = recommend_resume(rules, "data_ai", "Master Data Analyst")
    unknown = recommend_resume(rules, "", "Help Desk Technician")

    assert it.filename == "it-support_es.pdf" and it.path.parent.name == "resumes"
    assert data.filename == "data-ai_en.pdf" and data.label == "data-ai (inglés)"
    assert unknown.filename == "it-support_en.pdf"


def _insert(conn, status: Status = Status.DISCOVERED, reason: str = "") -> int:
    return db.insert_job(
        conn, make_job(), dedupe_key="k", status=status, status_reason=reason, role_family="x"
    )


def test_mark_applied_and_undo(conn) -> None:
    job_id = _insert(conn)

    marked = db.mark_applied(conn, job_id)
    assert marked.status == Status.SUBMITTED and marked.status_reason == db.APPLIED_MANUALLY
    assert db.list_jobs(conn, status=Status.DISCOVERED) == []

    reopened = db.mark_applied(conn, job_id, undo=True)
    assert reopened.status == Status.DISCOVERED and reopened.status_reason == ""


def test_mark_applied_also_works_on_a_job_the_filters_skipped(conn) -> None:
    job_id = _insert(conn, Status.SKIPPED, "title_excluded: senior")
    assert db.mark_applied(conn, job_id).status == Status.SUBMITTED


def test_mark_applied_errors(conn) -> None:
    with pytest.raises(KeyError):
        db.mark_applied(conn, 999)
    open_job = _insert(conn)
    with pytest.raises(InvalidTransition):  # nothing to undo
        db.mark_applied(conn, open_job, undo=True)
    db.mark_applied(conn, open_job)
    with pytest.raises(InvalidTransition):  # already applied
        db.mark_applied(conn, open_job)


def test_descriptions_by_id(conn) -> None:
    job_id = db.insert_job(
        conn, make_job(description="Soporte a usuarios"), dedupe_key="k", status=Status.DISCOVERED
    )
    assert db.descriptions(conn, [job_id, 404]) == {job_id: "Soporte a usuarios"}
    assert db.descriptions(conn, []) == {}
