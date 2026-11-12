"""Posting age (ADR-020): LinkedIn's saved alerts against its suggestions, Workday's relative
dates, fresh postings past a board's seniority label, and how the panel and the report show them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from conftest import FIXTURES, make_job
from jobbot import daily
from jobbot.core import db
from jobbot.core.models import Job
from jobbot.core.state import Status
from jobbot.discovery.email_alerts import EmailAlertSource, parse_linkedin
from jobbot.discovery.pipeline import rescreen
from jobbot.discovery.workday import posted_on
from jobbot.mail.gmail import MailMessage
from jobbot.panel import list_view, summary

RECEIVED = datetime(2026, 11, 9, 14, 0, tzinfo=UTC)


def _mail(name: str, received: datetime = RECEIVED, prefix: str = "") -> MailMessage:
    text = prefix + (FIXTURES / name).read_text(encoding="utf-8")
    return MailMessage(id=name, subject="", sender="x", text=text, html="", received_at=received)


class _Mail:
    def __init__(self, *messages: MailMessage) -> None:
        self.messages = {m.id: m for m in messages}

    def search(self, query: str, max_messages: int) -> list[str]:
        return list(self.messages)

    def get(self, message_id: str) -> MailMessage:
        return self.messages[message_id]


def _row(**overrides: object) -> db.JobRow:
    fields: dict[str, object] = {
        "id": 1,
        "source": "test",
        "company": "Acme",
        "title": "Help Desk Technician",
        "location": "Heredia",
        "url": "https://example.com/1",
        "status": Status.DISCOVERED,
        "status_reason": "",
        "role_family": "it_support",
        "first_seen_at": RECEIVED.isoformat(),
    }
    return db.JobRow(**{**fields, **overrides})


def _board_job(posted_at: datetime, title: str = "Analista de Soporte Tecnico") -> Job:
    return make_job(
        source="himalayas",
        ats="himalayas",
        title=title,
        location="Remote - LATAM",
        remote=True,
        description="Seniority: Senior. Soporte a usuarios de la empresa.",
        posted_at=posted_at,
    )


# --- LinkedIn emails ----------------------------------------------------------------------------


def test_linkedin_alert_skips_insight_lines_and_is_dated_by_the_email() -> None:
    jobs = parse_linkedin(_mail("email_linkedin_alert_es.txt"), "email:linkedin", "Costa Rica")

    assert [(j.title, j.company, j.location) for j in jobs] == [
        ("Técnico de Soporte TI", "Acme Corp", "Heredia"),
        ("Analista de Mesa de Ayuda", "Globex", "San José, Costa Rica"),
    ]
    assert all(j.posted_at == RECEIVED and j.posted_approx for j in jobs)
    assert not any(j.recommended for j in jobs)


def test_linkedin_suggestions_are_marked_and_undated() -> None:
    jobs = parse_linkedin(_mail("email_linkedin_similar.txt"), "email:linkedin", "Costa Rica")

    # Section headings before the title are skipped too ("Tus otros empleos guardados")
    assert [(j.title, j.company) for j in jobs] == [
        ("Help Desk Technician", "Initech"),
        ("Técnico de Soporte TI", "Acme Corp"),
    ]
    assert all(j.recommended and j.posted_at is None for j in jobs)


def test_an_alert_with_no_matches_only_brings_suggestions() -> None:
    prefix = "Empleos similares a tu alerta\nNo hay resultados para tu alerta, pero creemos que…\n"
    message = _mail("email_linkedin_alert_es.txt", prefix=prefix)

    assert all(j.recommended for j in parse_linkedin(message, "email:linkedin", "Costa Rica"))


def test_a_job_in_a_suggestion_and_an_alert_keeps_the_alert_date() -> None:
    earlier = RECEIVED - timedelta(hours=5)
    mail = _Mail(_mail("email_linkedin_similar.txt"), _mail("email_linkedin_alert_es.txt", earlier))
    source = EmailAlertSource("linkedin", mail, "q", lookback_days=14, max_messages=50)

    jobs = {j.ats_job_id: j for j in source.fetch()}

    assert not jobs["4100000001"].recommended and jobs["4100000001"].posted_at == earlier
    assert jobs["4100000003"].recommended


def test_a_known_job_keeps_its_first_date_and_loses_the_suggestion_mark(conn) -> None:
    db.insert_job(
        conn,
        make_job(ats="linkedin", ats_job_id="9", recommended=True),
        dedupe_key="k",
        status=Status.DISCOVERED,
    )
    seen = make_job(ats="linkedin", ats_job_id="9", posted_at=RECEIVED, posted_approx=True)

    db.note_posting(conn, seen)
    db.note_posting(conn, seen.model_copy(update={"posted_at": RECEIVED + timedelta(days=1)}))

    row = db.find_job(conn, "linkedin", "9")
    assert row.posted() == RECEIVED and row.posted_approx and not row.recommended


# --- Workday ------------------------------------------------------------------------------------


def test_workday_relative_ages() -> None:
    assert posted_on("Posted Today", RECEIVED) == RECEIVED
    assert posted_on("Posted Yesterday", RECEIVED) == RECEIVED - timedelta(days=1)
    assert posted_on("Posted 3 Days Ago", RECEIVED) == RECEIVED - timedelta(days=3)
    assert posted_on("Posted 30+ Days Ago", RECEIVED) == RECEIVED - timedelta(
        days=31
    )  # more than 30
    assert posted_on("Publicado hace 5 días", RECEIVED) == RECEIVED - timedelta(days=5)
    assert posted_on("Publicado hoy", RECEIVED) == RECEIVED
    assert posted_on("", RECEIVED) is None


# --- Filters ------------------------------------------------------------------------------------


def test_a_fresh_posting_passes_a_board_seniority_label(rules) -> None:
    now = datetime.now(UTC)

    fresh = rules.evaluate(_board_job(now - timedelta(hours=3)))
    old = rules.evaluate(_board_job(now - timedelta(days=3)))
    senior_title = rules.evaluate(_board_job(now - timedelta(hours=3), "Senior Support Analyst"))

    assert fresh.ok and fresh.reason == "fresh_seniority: seniority senior"
    assert not old.ok and old.reason == "description_excluded: seniority senior"
    assert not senior_title.ok  # a title that says senior stays out


def test_rescreen_judges_freshness_when_the_job_was_first_seen(conn, rules) -> None:
    first_seen = datetime.now(UTC) - timedelta(days=5)  # fresh then, not today
    job = _board_job(first_seen - timedelta(hours=2))
    db.insert_job(
        conn,
        job,
        dedupe_key="k",
        status=Status.SKIPPED,
        status_reason="description_excluded: seniority senior",
        role_family="it_support",
    )
    conn.execute("UPDATE jobs SET first_seen_at = ?", (first_seen.isoformat(),))

    assert rescreen(conn, rules)["reopened"] == 1
    row = db.find_job(conn, job.ats, job.ats_job_id)
    assert row.status is Status.DISCOVERED and row.status_reason.startswith("fresh_seniority")


# --- Report, notification and panel -------------------------------------------------------------


def test_posted_text() -> None:
    def text(ago: timedelta | None, approx: bool = False) -> str:
        posted = (RECEIVED - ago).isoformat() if ago is not None else None
        return daily.posted_text(_row(posted_at=posted, posted_approx=approx), RECEIVED)

    assert text(None) == "fecha de publicación desconocida"
    assert text(timedelta(minutes=20)) == "publicada hace menos de 1 h"
    assert text(timedelta(hours=5)) == "publicada hace 5 h"
    assert text(timedelta(days=3), approx=True) == "publicada hace ~3 días"
    assert text(timedelta(days=30), approx=True) == "publicada hace 30+ días"
    # A date without offset (elempleo) is read as UTC
    assert daily.posted_text(_row(posted_at="2026-11-08T00:00:00"), RECEIVED) == (
        "publicada hace 1 día"
    )


def test_linkedin_links_cover_the_last_fresh_hours_newest_first() -> None:
    (group, links), *_ = daily.linkedin_links()
    label, url = links[0]

    assert group == "Costa Rica"
    assert label == "help desk"
    assert url.startswith("https://www.linkedin.com/jobs/search/?")
    assert parse_qs(urlparse(url).query) == {
        "keywords": ["help desk"],
        "geoId": ["101739942"],
        "location": ["Costa Rica"],
        "f_TPR": ["r86400"],
        "sortBy": ["DD"],
    }


def _insert(conn, ats_job_id: str, title: str, **fields: object) -> int:
    reason = str(fields.pop("status_reason", ""))
    job = make_job(ats_job_id=ats_job_id, title=title, **fields)
    return db.insert_job(
        conn,
        job,
        dedupe_key=ats_job_id,
        status=Status.DISCOVERED,
        status_reason=reason,
        role_family="it_support",
    )


def test_report_lists_fresh_jobs_first_once_with_age_notes_and_linkedin(conn) -> None:
    now = datetime.now(UTC)
    _insert(
        conn,
        "fresh",
        "Analista de Soporte Tecnico",
        posted_at=now - timedelta(hours=2),
        status_reason="fresh_seniority: seniority senior",
    )
    _insert(conn, "suggested", "Help Desk Technician", recommended=True)
    pending = db.list_jobs(conn, status=Status.DISCOVERED)
    links = [
        ("Costa Rica", [("help desk", "https://www.linkedin.com/jobs/search/?keywords=help+desk")])
    ]

    page = daily.render_report(pending, [], pending, {}, datetime.now(), linkedin=links)

    assert page.index("Publicadas en las últimas 24 h (1)") < page.index("Soporte TI (1)")
    assert page.count("Analista de Soporte Tecnico") == 1
    assert "publicada hace 2 h · La bolsa la marca senior" in page
    assert "fecha de publicación desconocida · Recomendada por LinkedIn, puede ser vieja" in page
    assert "Buscar en LinkedIn" in page and "keywords=help+desk" in page


def test_notification_says_how_many_were_posted_in_the_last_day() -> None:
    message = daily.notification([_row()], [], {"it_support": "Soporte TI"}, fresh=2)

    assert message is not None
    assert message[1].splitlines()[0] == "2 publicadas en las últimas 24 h"


def test_pending_view_sorts_by_posting_date_and_leaves_suggestions_last(conn) -> None:
    now = datetime.now(UTC)
    _insert(conn, "a", "Service Desk Analyst", posted_at=now - timedelta(days=3))
    _insert(conn, "b", "Help Desk Technician", posted_at=now - timedelta(hours=1))
    _insert(conn, "c", "Soporte Técnico", recommended=True)
    undated = _insert(conn, "d", "IT Support Analyst")
    two_days_ago = (now - timedelta(days=2)).isoformat(timespec="seconds")
    conn.execute("UPDATE jobs SET first_seen_at = ? WHERE id = ?", (two_days_ago, undated))
    _insert(conn, "e", "Mesa de Ayuda")  # no date, first seen now: after the fresh one

    jobs = list_view(conn, "pending")

    assert [j["title"] for j in jobs] == [
        "Help Desk Technician",
        "Mesa de Ayuda",
        "IT Support Analyst",
        "Service Desk Analyst",
        "Soporte Técnico",
    ]
    fresh, _, _, _, suggested = jobs
    assert fresh["fresh"] and fresh["new"] and fresh["posted"] == "publicada hace 1 h"
    assert suggested["new"] and not suggested["fresh"]  # date unknown, first seen today
    assert suggested["notes"] == ["Recomendada por LinkedIn, puede ser vieja"]
    page = summary(conn)
    assert page["fresh"] == 1 and page["fresh_hours"] == 24
    assert page["linkedin"][0]["links"][0]["label"] == "help desk"
