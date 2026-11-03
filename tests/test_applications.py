"""Applications confirmed by email (ADR-018): parsing the confirmations and marking the jobs."""

from __future__ import annotations

from conftest import FIXTURES, make_job
from jobbot.cli import report_line
from jobbot.core import db
from jobbot.core.state import Status
from jobbot.discovery.applications import (
    NAME,
    Application,
    ConfirmationSource,
    parse_computrabajo_confirmation,
    parse_indeed_confirmation,
    parse_linkedin_confirmation,
    record_applications,
)
from jobbot.discovery.pipeline import run_source
from jobbot.mail.gmail import MailMessage


def _message(subject: str, text: str = "", html: str = "") -> MailMessage:
    return MailMessage(id="m1", subject=subject, sender="x", text=text, html=html)


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


LINKEDIN_SUBJECT = "Alex, se ha enviado tu solicitud a Initech"


# --- Parsers ------------------------------------------------------------------------------------


def test_linkedin_confirmation_is_the_first_posting_not_the_similar_ones() -> None:
    message = _message(LINKEDIN_SUBJECT, text=_fixture("email_linkedin_applied.txt"))
    app = parse_linkedin_confirmation(message)
    assert app is not None
    assert (app.site, app.title, app.company, app.location) == (
        "linkedin",
        "Analista de datos de operaciones",
        "Initech",
        "Heredia, Costa Rica",
    )
    assert (app.job.ats, app.job.ats_job_id) == ("linkedin", "4000000001")


def test_linkedin_confirmation_needs_the_company_of_the_subject() -> None:
    text = _fixture("email_linkedin_applied.txt")
    similar = "se ha enviado tu solicitud a Nimbus Cloud"  # the company of a similar job
    assert parse_linkedin_confirmation(_message(similar, text)) is None
    assert parse_linkedin_confirmation(_message("Nuevos empleos similares", text)) is None


def test_indeed_confirmation_reads_title_company_and_place() -> None:
    subject = "Postulación en Indeed: Especialista de Soporte Técnico"
    app = parse_indeed_confirmation(_message(subject, html=_fixture("email_indeed_applied.html")))
    assert app == Application(
        "indeed", "Especialista de Soporte Técnico", "Acme Servicios Ltd.", "CR Heredia Belén"
    )


def test_computrabajo_confirmation_has_only_the_title_in_the_subject() -> None:
    subject = "Seguimiento de tu candidatura para el puesto de Auxiliar de Mesa de Ayuda y redes"
    assert parse_computrabajo_confirmation(_message(subject)) == Application(
        "computrabajo", "Auxiliar de Mesa de Ayuda y redes"
    )
    other = _message("Alex, tienes novedades en tu postulación a Soporte TI")
    assert parse_computrabajo_confirmation(other) is None


# --- Recording ----------------------------------------------------------------------------------


def _add(conn, n: int, **job) -> int:
    job = make_job(ats_job_id=str(n), **job)
    return db.insert_job(conn, job, dedupe_key=str(n), status=Status.DISCOVERED)


def _status(conn, job_id: int) -> tuple[Status, str]:
    row = db.get_job(conn, job_id)
    return row.status, row.status_reason


def test_linkedin_application_marks_the_exact_posting(conn) -> None:
    app = parse_linkedin_confirmation(
        _message(LINKEDIN_SUBJECT, text=_fixture("email_linkedin_applied.txt"))
    )
    listed = db.insert_job(conn, app.job, dedupe_key="k", status=Status.DISCOVERED)
    similar = _add(conn, 2, title="Platform Engineer | LATAM", company="Nimbus Cloud")

    (marked,) = record_applications(conn, [app])

    assert marked.id == listed
    assert _status(conn, listed) == (Status.SUBMITTED, db.APPLIED_BY_EMAIL)
    assert _status(conn, similar) == (Status.DISCOVERED, "")


def test_application_never_listed_is_kept_once(conn) -> None:
    app = Application("indeed", "Técnico en Soporte", "Globex Equipos SA", "Escazú, San José")

    (added,) = record_applications(conn, [app])
    assert (added.source, added.status, added.status_reason) == (
        NAME,
        Status.SUBMITTED,
        db.APPLIED_BY_EMAIL,
    )
    assert record_applications(conn, [app]) == []  # the same email on the next run


def test_application_already_marked_from_an_alert_without_company_is_not_added(conn) -> None:
    job_id = _add(
        conn,
        1,
        title="Help Desk Escalation Coordinator",
        company="(Indeed)",
        source="email:indeed",
    )
    db.mark_applied(conn, job_id)
    app = Application("indeed", "Help Desk Escalation Coordinator", "Nimbus Cloud", "Costa Rica")

    assert record_applications(conn, [app]) == []
    assert len(db.applied_jobs(conn)) == 1


def test_indeed_application_marks_same_company_and_title_from_any_source(conn) -> None:
    title = "Especialista de Soporte Técnico"
    same = _add(conn, 1, title=title, company="Acme Servicios Ltd", source="workday:acme")
    other = _add(conn, 2, title=title, company="Otra Empresa")
    app = Application("indeed", title, "Acme Servicios Ltd.", "Heredia")

    assert [r.id for r in record_applications(conn, [app])] == [same]
    assert _status(conn, other) == (Status.DISCOVERED, "")


def test_title_only_application_needs_a_single_job_of_that_site(conn) -> None:
    app = Application("computrabajo", "Técnico TI")
    one = _add(conn, 1, title="Técnico TI", company="Initech", source="email:computrabajo")
    _add(conn, 2, title="Técnico TI", company="Globex", source="email:linkedin")

    assert [r.id for r in record_applications(conn, [app])] == [one]

    two = _add(conn, 3, title="Técnico TI", company="Globex", source="email:computrabajo")
    three = _add(conn, 4, title="Técnico TI", company="Initech", source="email:computrabajo")
    assert record_applications(conn, [app]) == []  # two candidates: no guessing
    assert _status(conn, two)[0] == _status(conn, three)[0] == Status.DISCOVERED


def test_undone_email_mark_is_not_redone(conn) -> None:
    job_id = _add(conn, 1, title="Técnico TI", company="Initech", source="email:computrabajo")
    app = Application("computrabajo", "Técnico TI")
    record_applications(conn, [app])

    db.mark_applied(conn, job_id, undo=True)

    assert record_applications(conn, [app]) == []
    assert _status(conn, job_id) == (Status.DISCOVERED, db.REOPENED_MANUALLY)


# --- Source -------------------------------------------------------------------------------------


class FakeMail:
    def __init__(self, by_sender: dict[str, list[MailMessage]]) -> None:
        self.by_sender = by_sender

    def search(self, query: str, max_messages: int) -> list[str]:
        return [
            f"{sender}:{i}"
            for sender, messages in self.by_sender.items()
            if sender in query
            for i in range(len(messages))
        ][:max_messages]

    def get(self, message_id: str) -> MailMessage:
        sender, _, index = message_id.rpartition(":")
        return self.by_sender[sender][int(index)]


def test_confirmation_source_records_applications_during_a_run(conn, rules) -> None:
    computrabajo = _message("Seguimiento de tu candidatura para el puesto de Técnico TI")
    linkedin = _message(LINKEDIN_SUBJECT, text=_fixture("email_linkedin_applied.txt"))
    mail = FakeMail({"postulaciones@": [computrabajo], "jobs-noreply@": [linkedin]})
    source = ConfirmationSource(
        mail,
        {
            "computrabajo": "from:postulaciones@computrabajo.com",
            "linkedin": "from:jobs-noreply@linkedin.com",
            "elempleo": "from:elempleo.com",  # no parser: ignored
        },
        lookback_days=14,
        max_messages=50,
    )
    _add(conn, 1, title="Técnico TI", company="Initech", source="email:computrabajo")

    report = run_source(source, conn, rules)

    assert (report.confirmations, report.marked_applied, report.error) == (2, 2, "")
    assert " ".join(report_line(NAME, report).split()) == (
        f"{NAME} confirmaciones: 2 marcadas como postuladas: 2"
    )
    assert len(db.applied_jobs(conn)) == 2
