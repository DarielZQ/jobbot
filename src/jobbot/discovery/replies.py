"""Employers' replies read from the candidate's Gmail (ADR-034).

A rejection that names the company and the position closes that application by itself. One
that names only the company, and an invitation to an interview, become a question in the
panel's Decisiones tab: the candidate confirms before anything changes. Read-only, like the
alert feeds and the confirmations (ADR-012, ADR-018).

Which application a reply is about:
- LinkedIn's rejection says it in the subject: "Tu solicitud para el puesto de <title> en
  <company>".
- Any other: the company must be in the sender or the subject (its body also names the job
  boards, the ATS and the candidate's own words), and the title anywhere in the email.
"""

from __future__ import annotations

import html as html_lib
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass

from jobbot.core import db
from jobbot.core.db import JobRow
from jobbot.core.state import Status
from jobbot.discovery.base import Source
from jobbot.discovery.email_alerts import MailReader
from jobbot.grill import signals
from jobbot.mail.gmail import MailMessage
from jobbot.matching.dedupe import is_placeholder
from jobbot.matching.normalize import normalize_company, normalize_text, normalize_title

NAME = "email:respuestas"
# Replies are read again every run over `lookback_days`: two weeks of them can pass 50
MAX_MESSAGES = 200
REJECTED, INTERVIEW = "rejected", "interview"
# Set on an application closed by an employer's email; the candidate's own marks say "manual".
REJECTED_BY_EMAIL = "rejected_by_email"
CLOSED_BY_REPLY = "Cerrada: llegó el rechazo"  # answer given to its pending questions

# On normalized text (lowercase, no accents). Phrases that state a decision, not the ones an
# acknowledgment uses for what may happen ("if you are not selected...").
_REJECTION = re.compile(
    r"\b(?:application_rejected"
    r"|(?:decided|decision) (?:not to|to not) (?:move forward|proceed|progress|continue)"
    r"|(?:not|won t|will not|unable to|are not) (?:be )?(?:able to )?"
    r"(?:moving|move|proceed|proceeding|progress|progressing) (?:forward )?with your"
    r" (?:application|candidacy)"
    r"|move forward with (?:other|another) (?:candidates?|applicants?)"
    r"|move forward with (?:candidates?|applicants?) (?:whose|who)"
    r"|(?:pursue|progress with|proceed with) (?:other|another|a different)"
    r" (?:candidates?|applicants?)"
    r"|(?:have|has) not been selected|regret to inform"
    r"|no longer (?:actively )?(?:hiring|recruiting)"
    r"|position (?:has (?:now )?been|was|is) (?:closed|filled)"
    r"|no (?:continuar|avanzar|seguir adelante) con (?:tu|su) (?:candidatura|solicitud|proceso"
    r"|postulacion)"
    r"|decidido (?:no (?:continuar|avanzar|seguir)|avanzar sin (?:tu|su) postulacion)"
    r"|no continuaremos con (?:tu|su) proceso)\b"
)
_INVITATION = re.compile(
    r"\b(?:interview invitation|invitation (?:for|to) an? (?:initial |first )?interview"
    r"|invitacion a (?:una )?entrevista|agendar(?:te)? una entrevista"
    r"|schedule (?:a|an) (?:call|interview) with you|book a meeting)\b"
)
# Earlier in the same sentence, it turns a decision into a condition
_CONDITION = re.compile(r"\b(?:without|unless|if|si no|a menos que|en caso de)\b")
_LINKEDIN_REJECTION = re.compile(r"tu solicitud para el puesto de\s+(.+?)\s+en\s+(.+)$", re.I)
_TAG = re.compile(r"<[^>]+>")
_STYLE = re.compile(r"<(style|script)\b.*?</\1>", re.I | re.S)


@dataclass(frozen=True)
class Reply:
    kind: str  # REJECTED | INTERVIEW
    message_id: str
    subject: str
    header: str  # sender and subject, normalized: where the company must be named
    text: str  # subject and body, normalized like a title: where the title must be
    company: str = ""  # only when the email states it plainly (LinkedIn)
    title: str = ""


def _body(message: MailMessage) -> str:
    return message.text or html_lib.unescape(_TAG.sub(" ", _STYLE.sub(" ", message.html)))


def classify(message: MailMessage) -> Reply | None:
    """A rejection or an interview invitation; None for anything else (acknowledgments,
    alerts, reminders)."""
    raw = f"{message.subject}\n{_body(message)}"
    text = normalize_text(raw)
    common = {
        "message_id": message.id,
        "subject": message.subject,
        "header": normalize_text(f"{message.sender} {message.subject}"),
        "text": normalize_title(raw),
    }
    # LinkedIn's rejection says so only in its tracking links ("application_rejected")
    linkedin = _LINKEDIN_REJECTION.search(message.subject)
    if linkedin and "application_rejected" in raw:
        title, company = linkedin.group(1).strip(), linkedin.group(2).strip()
        return Reply(REJECTED, company=company, title=title, **common)
    if _decided(_REJECTION, text):
        return Reply(REJECTED, **common)
    if _decided(_INVITATION, text):
        return Reply(INTERVIEW, **common)
    return None


def _decided(pattern: re.Pattern[str], text: str) -> bool:
    """The phrase states what happened, not a condition: "without completing the required
    steps we won't be able to proceed with your application" is a reminder."""
    for match in pattern.finditer(text):
        sentence = text[: match.start()].rsplit(".", 1)[-1]
        if not _CONDITION.search(sentence):
            return True
    return False


def _named(words: str, text: str) -> bool:
    return bool(words) and re.search(rf"(?<!\w){re.escape(words)}(?!\w)", text) is not None


_OPEN = (Status.SUBMITTED, Status.CONFIRMED, Status.UNCERTAIN)  # applied, no outcome yet
# A title needs a few words to point to one application by itself ("Service Desk" does not)
_MIN_TITLE_WORDS = 3


def _most_specific(jobs: list[JobRow]) -> list[JobRow]:
    """The longest titles the email names: "Support Engineer" is also inside "Support
    Engineer I - Partner Tech". Copies of one opening share their title, so they all stay."""
    titles = {normalize_title(j.title) for j in jobs}
    return [
        j
        for j in jobs
        if not any(normalize_title(j.title) in t and normalize_title(j.title) != t for t in titles)
    ]


def candidates(conn: sqlite3.Connection, reply: Reply) -> tuple[list[JobRow], list[JobRow]]:
    """(open applications the reply names by company and title: closed without asking,
    an open application it is probably about: asked in Decisiones)."""
    applied = db.applied_jobs(conn)
    if reply.company:  # LinkedIn: both are given
        company, title = normalize_company(reply.company), normalize_title(reply.title)
        same = [
            r
            for r in applied
            if normalize_company(r.company) == company and normalize_title(r.title) == title
        ]
        return [r for r in same if r.status in _OPEN], []
    at_company = [
        r
        for r in applied
        if not is_placeholder(r.company) and _named(normalize_company(r.company), reply.header)
    ]
    if titled := _most_specific(
        [r for r in at_company if _named(normalize_title(r.title), reply.text)]
    ):
        # Already closed by an earlier copy of the same email: nothing left to do or ask
        return [r for r in titled if r.status in _OPEN], []
    if at_company:
        # The only application at that company, and still open: probably that one
        only = at_company if len(at_company) == 1 and at_company[0].status in _OPEN else []
        return [], only
    # A sender that is not the company's name ("MOVE"), with a precise title in the subject
    subject = normalize_title(reply.subject)
    in_subject = [
        r
        for r in applied
        if r.status in _OPEN
        and len(normalize_title(r.title).split()) >= _MIN_TITLE_WORDS
        and _named(normalize_title(r.title), subject)
    ]
    return [], in_subject if len(in_subject) == 1 else []


def _question(reply: Reply, job: JobRow) -> dict:
    what = "un rechazo" if reply.kind == REJECTED else "una invitación a entrevista"
    yes = signals.CLOSE if reply.kind == REJECTED else signals.TO_INTERVIEW
    return {
        "key": f"{reply.kind}:{job.id}:{reply.message_id}",
        "kind": f"reply_{reply.kind}",
        "question": (
            f"Llegó {what} de {job.company}: «{reply.subject}». ¿Es de tu postulación a "
            f"«{job.title}» (#{job.id})?"
        ),
        "options": [yes, signals.NOT_THIS_ONE],
        # JobBot only guessed which application it is: the candidate checks the email
        "recommended": "",
        "reason": "El correo no dice el puesto, o lo dice con otro nombre: revísalo antes.",
    }


def record_replies(conn: sqlite3.Connection, replies: Iterable[Reply]) -> tuple[int, int]:
    """Close the applications rejections name, and ask about the rest. Returns (closed,
    questions queued). Running it again over the same emails changes nothing."""
    replies = list(replies)
    closed, questions = 0, []
    # The rejections that name their position first: a vaguer one is then asked only about
    # what is still open ("Thanks for your interest in Acme" after Acme's precise one)
    for reply in replies:
        if reply.kind == REJECTED:
            for job in candidates(conn, reply)[0]:
                db.set_status(conn, job.id, Status.REJECTED, REJECTED_BY_EMAIL)
                signals.settle(conn, [job.id], CLOSED_BY_REPLY)
                closed += 1
    for reply in replies:
        named, probable = candidates(conn, reply)
        if reply.kind == INTERVIEW:  # always asked: a wrong "Entrevista" hides a pending job
            questions += [_question(reply, job) for job in (named[:1] or probable)]
        elif not named:
            questions += [_question(reply, job) for job in probable]
    return closed, signals.propose(conn, questions)


class ReplySource(Source):
    """Reads employers' replies and records them (see `run_source`). It lists no jobs."""

    name = NAME

    def __init__(
        self, mail: MailReader, query: str, *, lookback_days: int, max_messages: int
    ) -> None:
        super().__init__(None)
        self._mail = mail
        self._query = f"({query}) newer_than:{lookback_days}d"
        self._max_messages = max_messages

    def fetch(self) -> Iterable:
        return []

    def replies(self) -> list[Reply]:
        found = []
        for message_id in self._mail.search(self._query, self._max_messages):
            if (reply := classify(self._mail.get(message_id))) is not None:
                found.append(reply)
        return found

    def record(self, conn: sqlite3.Connection) -> tuple[int, int, int]:
        """(replies read, applications closed, questions queued)."""
        replies = self.replies()
        return (len(replies), *record_replies(conn, replies))
