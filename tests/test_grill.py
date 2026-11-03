"""grill-me (ADR-019): interview rounds, applying answers to YAML, and background decisions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from conftest import make_job
from jobbot import cli, grill
from jobbot.config import load_search_rules, load_settings
from jobbot.core import db
from jobbot.core.state import Status
from jobbot.discovery.pipeline import SourceReport
from jobbot.grill import apply, signals

TOPIC = grill.load_topic("setup-profile")


def _ids(questions) -> list[str]:
    return [q.id for q in questions]


def test_rounds_follow_dependencies_and_conditions() -> None:
    first = grill.frontier(TOPIC.questions, {})
    assert "max_level" not in _ids(first) and "local_area" not in _ids(first)

    answers = {q.id: "x" for q in first} | {
        "families": "Soporte TI",
        "modality": "Remoto, y presencial o híbrido en mi zona",
    }
    assert _ids(grill.frontier(TOPIC.questions, answers)) == ["max_level", "local_area"]

    remote_only = answers | {"modality": "Solo remoto", "max_level": "Hasta nivel 2"}
    assert grill.frontier(TOPIC.questions, remote_only) == []  # local_area is never asked


def test_parse_accepts_letters_text_and_enter_for_the_recommended_option() -> None:
    by_id = {q.id: q for q in TOPIC.questions}
    assert grill.parse(by_id["families"], "") == "Soporte TI"  # recommended
    assert grill.parse(by_id["families"], "b") == "Soporte TI y datos"
    assert grill.parse(by_id["families"], "z") is None
    assert grill.parse(by_id["country"], "") is None  # a fact: no recommendation, must answer
    assert grill.parse(by_id["phone"], "") == ""  # optional free answer
    assert grill.parse(by_id["name"], "Alex Ejemplo") == "Alex Ejemplo"


def test_facts_about_the_user_have_no_recommended_answer() -> None:
    by_id = {q.id: q for q in TOPIC.questions}
    for fact in ("country", "languages", "name", "email", "phone", "local_area"):
        assert not by_id[fact].recommended


def test_interview_asks_round_by_round_and_the_free_answer_of_other() -> None:
    replies = iter(
        [
            "f",
            "Honduras",
            "",
            "",
            "a",
            "Alex Ejemplo",
            "dariel@example.invalid",
            "",
            "",
            "Tegucigalpa",
        ]
    )
    output: list[str] = []

    answers = grill.interview(TOPIC, ask=lambda _: next(replies), out=output.append)

    assert answers["country"] == "Honduras"  # "Otro" asks for the name
    assert answers["families"] == "Soporte TI"
    assert answers["max_level"] == "Hasta nivel 2"
    assert answers["local_area"] == "Tegucigalpa"
    assert any("➡️ Recomendada: Hasta nivel 2" in line for line in output)


def test_plan_shows_changes_and_saves_them_keeping_comments(home: Path) -> None:
    answers = {
        "country": "México",
        "families": "Soporte TI",
        "max_level": "Solo nivel 1",
        "modality": "Remoto, y presencial o híbrido en mi zona",
        "local_area": "Monterrey, Guadalajara",
        "languages": "Español, inglés y portugués",
        "name": "Alex Ejemplo",
        "email": "dariel@example.invalid",
        "phone": "",
    }
    plan = apply.plan(answers, TOPIC.questions)
    assert "config/settings.yaml: region.country = 'Mexico'" in plan.changes
    assert load_settings().region.country == "Costa Rica"  # nothing written yet

    plan.save()

    region = load_settings().region
    assert (region.country, region.country_code, region.utc_offset) == ("Mexico", "MEX", -6)
    search = load_search_rules()
    assert list(search.role_families) == ["it_support"]
    assert apply.LEVEL_2[0] in search.title.exclude
    assert r"\b(monterrey|guadalajara)\b" in search.location.local
    assert not any("portug" in p for p in search.title.exclude)
    assert "# Dónde buscas trabajo" in (home / "config" / "settings.yaml").read_text("utf-8")


def test_remote_only_clears_the_local_area() -> None:
    plan = apply.plan({"modality": "Solo remoto"}, TOPIC.questions)
    plan.save()
    assert load_search_rules().location.local == []


# --- Background decisions -----------------------------------------------------------------------


def _applied_long_ago(conn, n: int = 1) -> int:
    job_id = db.insert_job(
        conn, make_job(ats_job_id=str(n)), dedupe_key=str(n), status=Status.DISCOVERED
    )
    db.mark_applied(conn, job_id)
    old = (datetime.now(UTC) - timedelta(days=30)).isoformat(timespec="seconds")
    conn.execute("UPDATE jobs SET updated_at = ? WHERE id = ?", (old, job_id))
    return job_id


def test_stale_application_is_asked_once_and_closed_on_request(conn) -> None:
    job_id = _applied_long_ago(conn)

    assert signals.refresh(conn) == 1
    assert signals.refresh(conn) == 0  # never queued twice
    (decision,) = signals.pending(conn)
    assert decision.recommended == signals.CLOSE

    signals.answer(conn, decision.id, signals.CLOSE)

    assert db.get_job(conn, job_id).status == Status.REJECTED
    assert signals.pending(conn) == []


def test_at_most_three_new_questions_a_day(conn) -> None:
    for n in range(5):
        _applied_long_ago(conn, n)
    assert signals.refresh(conn) == 3
    assert signals.refresh(conn) == 0
    tomorrow = datetime.now(UTC) + timedelta(days=1)
    assert signals.refresh(conn, now=tomorrow) == 2


def test_failing_source_can_be_disabled(conn) -> None:
    signals.record_runs(conn, [("workday:acme", SourceReport(error="HTTPStatusError: 500"))] * 3)
    signals.record_runs(conn, [("workday:ok", SourceReport())] * 3)

    signals.refresh(conn)
    (decision,) = signals.pending(conn)
    assert decision.key == "failing:workday:acme"

    signals.answer(conn, decision.id, signals.DISABLE)
    assert load_settings().disabled_sources == ["workday:acme"]


def test_skill_many_postings_ask_for_is_asked_without_a_recommendation(conn) -> None:
    for n in range(5):
        job = make_job(ats_job_id=str(n), description="Soporte con Zendesk y Windows.")
        db.insert_job(conn, job, dedupe_key=str(n), status=Status.DISCOVERED)

    signals.refresh(conn)
    (decision,) = signals.pending(conn)
    assert decision.key == "skill:Zendesk" and decision.recommended == ""

    with pytest.raises(ValueError):
        signals.answer(conn, decision.id, "Quizás")
    signals.answer(conn, decision.id, signals.LEARNING)
    facts = (Path(load_settings().db_path()).parents[1] / "profile" / "facts.yaml").read_text(
        encoding="utf-8"
    )
    assert "Zendesk" in facts


def test_cli_answers_pending_decisions(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = db.connect(load_settings().db_path())
    _applied_long_ago(conn)
    signals.refresh(conn)
    monkeypatch.setattr("builtins.input", lambda _: "")  # Enter: the recommended option

    assert cli.main(["grill", "pendientes"]) == 0
    assert "Vacante cerrada como sin respuesta." in capsys.readouterr().out
    assert signals.pending(conn) == []


def test_panel_lists_and_answers_decisions(conn) -> None:
    from jobbot import panel

    _applied_long_ago(conn)
    signals.refresh(conn)
    (item,) = panel.decisions_view(conn)
    assert item["options"] == (signals.CLOSE, signals.WAIT)
    assert panel.summary(conn)["counts"]["decisions"] == 1

    signals.answer(conn, item["id"], signals.WAIT)
    assert panel.decisions_view(conn) == []
