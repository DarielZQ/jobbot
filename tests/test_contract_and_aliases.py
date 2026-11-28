"""ADR-033: the contract or payroll note, and company aliases for duplicates."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from conftest import make_job
from jobbot import daily
from jobbot.config import load_search_rules
from jobbot.core import db
from jobbot.core.state import Status
from jobbot.discovery.pipeline import rescreen
from jobbot.matching.dedupe import applied_twins, dedupe_key
from jobbot.matching.normalize import normalize_company, set_company_aliases
from jobbot.matching.rules import CONTRACT_ROLE, PAYROLL_ROLE, RuleSet


@pytest.mark.parametrize(
    ("title", "description"),
    [
        ("IT Support Specialist (Contract)", ""),
        ("Help Desk Technician - Temporary", ""),
        ("Técnico de Soporte (contrato por 6 meses)", ""),
        ("IT Support Specialist", "This is a contract role for 12 months."),
        ("IT Support Specialist", "You will work as an independent contractor."),
        ("Soporte TI", "Contratación por servicios profesionales, debe facturar."),
    ],
)
def test_a_contract_job_passes_with_a_note(rules, title: str, description: str) -> None:
    result = rules.evaluate(make_job(title=title, description=description))

    assert result.ok
    assert result.reason.startswith(CONTRACT_ROLE)


@pytest.mark.parametrize(
    "description",
    [
        "Puesto en planilla con todas las garantías de ley.",
        "Contrato por tiempo indefinido.",
        "This is a full-time permanent position.",
    ],
)
def test_a_payroll_job_passes_with_a_note(rules, description: str) -> None:
    result = rules.evaluate(make_job(title="IT Support Analyst", description=description))

    assert result.ok
    assert result.reason.startswith(PAYROLL_ROLE)


@pytest.mark.parametrize(
    "description",
    [
        "Coordinate repairs with vendors and contractors.",
        "Review service contracts and warranties.",
        "Manejo de planillas de Excel.",
    ],
)
def test_contracts_the_job_handles_get_no_note(rules, description: str) -> None:
    result = rules.evaluate(make_job(title="IT Support Analyst", description=description))

    assert result.ok and result.reason == ""


def test_contract_to_hire_is_a_contract_not_payroll(rules) -> None:
    job = make_job(description="Contract to hire: you join our payroll after six months.")

    assert rules.evaluate(job).reason.startswith(CONTRACT_ROLE)


def _row(reason: str) -> db.JobRow:
    return db.JobRow(
        id=1,
        source="s",
        company="Acme",
        title="IT Support Analyst",
        location="Heredia, Costa Rica",
        url="u",
        status=Status.DISCOVERED,
        status_reason=reason,
        role_family="it_support",
        first_seen_at=datetime.now(UTC).isoformat(),
    )


def test_the_notes_say_contract_or_payroll_in_plain_words() -> None:
    assert daily.job_notes(_row(f"{CONTRACT_ROLE}: contract")) == [
        "Por contrato o temporal: confirma si es en planilla"
    ]
    assert daily.job_notes(_row(f"{PAYROLL_ROLE}: en planilla")) == ["En planilla"]


def test_aliases_name_one_company() -> None:
    assert normalize_company("Hewlett Packard Enterprise") != normalize_company("HPE")

    load_search_rules()  # the preset lists HPE and P&G

    assert normalize_company("Hewlett Packard Enterprise") == normalize_company("HPE")
    assert normalize_company("P&G") == normalize_company("Procter & Gamble")
    assert normalize_company("HP") != normalize_company("HPE")  # another company


def test_aliases_find_the_same_opening_and_the_one_applied_to() -> None:
    set_company_aliases([["HPE", "Hewlett Packard Enterprise"]])
    workday = make_job(company="HPE", title="NAC Support Agent L1", location="Heredia")
    indeed = make_job(company="Hewlett Packard Enterprise", title="NAC Support Agent L1")

    assert dedupe_key(workday) == dedupe_key(indeed.model_copy(update={"location": "Heredia"}))
    applied = replace(_row(""), id=2, company="HPE")
    pending = replace(_row(""), id=3, company="Hewlett Packard Enterprise")
    assert applied_twins([pending], [applied]) == {3: applied}


def _store(conn, company: str, ats_job_id: str, status: Status = Status.DISCOVERED) -> int:
    job = make_job(ats_job_id=ats_job_id, company=company, title="NAC Support Agent L1")
    reason = db.APPLIED_MANUALLY if status is Status.SUBMITTED else ""
    return db.insert_job(
        conn,
        job,
        dedupe_key=dedupe_key(job),  # before the alias existed
        status=status,
        status_reason=reason,
        role_family="it_support",
    )


def test_rescreen_joins_open_copies_once_an_alias_names_them(conn) -> None:
    first = _store(conn, "HPE", "a")
    second = _store(conn, "Hewlett Packard Enterprise", "b")

    changes = rescreen(conn, RuleSet(load_search_rules()))

    assert changes["rekeyed"] == 1 and changes["duplicates"] == 1
    assert db.get_job(conn, first).status == Status.DISCOVERED
    copy = db.get_job(conn, second)
    assert (copy.status, copy.status_reason) == (Status.SKIPPED, f"duplicate_of: {first}")


def test_rescreen_drops_an_open_copy_of_a_job_already_applied_to(conn) -> None:
    pending = _store(conn, "Hewlett Packard Enterprise", "a")
    applied = _store(conn, "HPE", "b", Status.SUBMITTED)

    rescreen(conn, RuleSet(load_search_rules()))

    assert db.get_job(conn, pending).status_reason == f"duplicate_of: {applied}"
    assert db.get_job(conn, applied).status == Status.SUBMITTED


def test_rescreen_without_new_aliases_changes_no_key(conn) -> None:
    _store(conn, "Acme", "a")

    assert "rekeyed" not in rescreen(conn, RuleSet(load_search_rules()))
