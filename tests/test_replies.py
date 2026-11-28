"""ADR-034: employers' replies close applications or ask in Decisiones. Fictitious emails."""

from __future__ import annotations

from conftest import make_job
from jobbot.core import db
from jobbot.core.state import Status
from jobbot.discovery.replies import (
    INTERVIEW,
    REJECTED,
    REJECTED_BY_EMAIL,
    ReplySource,
    classify,
    record_replies,
)
from jobbot.grill import signals
from jobbot.mail.gmail import MailMessage


def _mail(text: str, subject: str = "Update on your application", sender: str = "") -> MailMessage:
    return MailMessage("m1", subject, sender or "Acme Talent <jobs@acme.example.com>", text, "")


def _applied(conn, company: str, title: str, ats_job_id: str = "1") -> int:
    job = make_job(ats_job_id=ats_job_id, company=company, title=title)
    return db.insert_job(
        conn, job, dedupe_key=ats_job_id, status=Status.SUBMITTED, status_reason="applied_manually"
    )


REJECTION = (
    "Thank you for applying to the IT Support Analyst position at Acme. After careful "
    "consideration, we have decided not to move forward with your application."
)


def test_rejections_in_english_and_spanish_are_read() -> None:
    assert classify(_mail(REJECTION)).kind == REJECTED
    spanish = (
        "Gracias por postular. En esta ocasión hemos decidido no continuar con tu candidatura."
    )
    assert classify(_mail(spanish)).kind == REJECTED
    other = "We have reviewed your profile and decided to pursue other candidates for this role."
    assert classify(_mail(other)).kind == REJECTED


def test_acknowledgments_and_reminders_are_not_replies() -> None:
    received = (
        "We received your application. If you are not selected for this position, keep an eye "
        "on our jobs page. If your profile aligns, we will invite you to an interview."
    )
    reminder = "Without completing the video, we won't be able to proceed with your application."
    assert classify(_mail(received)) is None
    assert classify(_mail(reminder)) is None


def test_an_interview_invitation_is_read() -> None:
    text = "We reviewed your application and would like to schedule a call with you."
    assert classify(_mail(text)).kind == INTERVIEW


def test_linkedin_says_company_and_title_in_the_subject() -> None:
    reply = classify(
        _mail(
            "Tu actualización de Acme https://www.linkedin.com/help?trk=email_jobs_application_rejected_01",
            subject="Tu solicitud para el puesto de Help Desk Technician en Acme Corp",
            sender="LinkedIn <jobs-noreply@linkedin.com>",
        )
    )
    assert (reply.kind, reply.title, reply.company) == (
        REJECTED,
        "Help Desk Technician",
        "Acme Corp",
    )


def test_a_rejection_naming_company_and_title_closes_that_application(conn) -> None:
    named = _applied(conn, "Acme", "IT Support Analyst", "a")
    other = _applied(conn, "Acme", "Data Analyst", "b")
    signals.propose(
        conn,
        [
            {
                "key": f"stale:{named}",
                "kind": "stale",
                "question": "q",
                "options": [signals.CLOSE],
                "recommended": "",
                "reason": "",
            }
        ],
    )

    assert record_replies(conn, [classify(_mail(REJECTION))]) == (1, 0)

    closed = db.get_job(conn, named)
    assert (closed.status, closed.status_reason) == (Status.REJECTED, REJECTED_BY_EMAIL)
    assert db.get_job(conn, other).status == Status.SUBMITTED
    assert signals.pending(conn) == []  # its "sin respuesta" question was answered by the reply


def test_the_same_email_twice_changes_nothing_more(conn) -> None:
    _applied(conn, "Acme", "IT Support Analyst", "a")
    _applied(conn, "Acme", "Data Analyst", "b")
    reply = classify(_mail(REJECTION))

    assert record_replies(conn, [reply, reply]) == (1, 0)
    assert record_replies(conn, [reply]) == (0, 0)


def test_the_most_specific_title_is_the_one_closed(conn) -> None:
    general = _applied(conn, "Acme", "Support Engineer", "a")
    specific = _applied(conn, "Acme", "Support Engineer I - Partner Tech", "b")
    text = (
        "Your application for Support Engineer I - Partner Tech: "
        "we decided to pursue other candidates."
    )

    record_replies(conn, [classify(_mail(text))])

    assert db.get_job(conn, specific).status == Status.REJECTED
    assert db.get_job(conn, general).status == Status.SUBMITTED


def test_a_rejection_without_the_title_asks_first(conn) -> None:
    job_id = _applied(conn, "Acme", "IT Support Analyst")
    vague = "Thanks for your time. We decided to move forward with other candidates."

    assert record_replies(conn, [classify(_mail(vague))]) == (0, 1)
    assert db.get_job(conn, job_id).status == Status.SUBMITTED
    question = signals.pending(conn)[0]
    assert question.kind == "reply_rejected" and question.recommended == ""

    signals.answer(conn, question.id, signals.CLOSE)

    assert db.get_job(conn, job_id).status_reason == REJECTED_BY_EMAIL


def test_a_vague_rejection_asks_nothing_when_the_company_has_several(conn) -> None:
    _applied(conn, "Acme", "IT Support Analyst", "a")
    _applied(conn, "Acme", "Data Analyst", "b")
    vague = "We decided to move forward with other candidates."

    assert record_replies(conn, [classify(_mail(vague))]) == (0, 0)


def test_an_invitation_asks_before_moving_to_interviews(conn) -> None:
    job_id = _applied(conn, "Acme", "IT Support Analyst")
    text = (
        "We reviewed your application for IT Support Analyst and want to schedule a call with you."
    )

    assert record_replies(conn, [classify(_mail(text))]) == (0, 1)
    question = signals.pending(conn)[0]
    signals.answer(conn, question.id, signals.TO_INTERVIEW)

    assert db.get_job(conn, job_id).status == Status.INTERVIEW


def test_an_invitation_from_another_name_is_found_by_its_title(conn) -> None:
    job_id = _applied(conn, "Northwind Business", "AI Operations Specialist")
    invite = _mail(
        "We would like to schedule a call with you.",
        subject="Interview Invitation | AI Operations Specialist Role at NW",
        sender="recruitment@nw.example.com",
    )

    record_replies(conn, [classify(invite)])

    assert f"(#{job_id})" in signals.pending(conn)[0].question


class FakeMail:
    def __init__(self, messages: list[MailMessage]) -> None:
        self.messages = {m.id: m for m in messages}
        self.queries: list[str] = []

    def search(self, query: str, max_messages: int) -> list[str]:
        self.queries.append(query)
        return list(self.messages)

    def get(self, message_id: str) -> MailMessage:
        return self.messages[message_id]


def test_reply_source_reads_the_query_window_and_records(conn) -> None:
    _applied(conn, "Acme", "IT Support Analyst")
    mail = FakeMail(
        [_mail(REJECTION), MailMessage("m2", "Thanks for applying", "x", "Received.", "")]
    )
    source = ReplySource(mail, "from:me", lookback_days=14, max_messages=200)

    assert source.record(conn) == (1, 1, 0)
    assert mail.queries == ["(from:me) newer_than:14d"]
