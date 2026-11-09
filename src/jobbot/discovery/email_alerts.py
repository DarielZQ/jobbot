"""Job alerts read from the candidate's own Gmail (ADR-005, ADR-012).

Feeds: LinkedIn, CompuTrabajo, Indeed and elempleo. The bot never visits those sites: it only
reads alert emails they already sent, and lists the jobs for the candidate to apply manually
(assisted mode).

The exact email layouts were not available when this was written: parsers prefer the text part
and fall back to links in the HTML. Validate with `uv run jobbot alerts-sample`.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import re
from collections.abc import Callable, Iterable
from typing import Protocol
from urllib.parse import unquote

from jobbot.core.models import Job
from jobbot.discovery.base import Source
from jobbot.mail.gmail import MailMessage
from jobbot.matching.normalize import strip_accents

LINKEDIN_JOB = re.compile(r"https?://(?:[\w-]+\.)?linkedin\.com/(?:comm/)?jobs/view/(\d+)", re.I)
COMPUTRABAJO_JOB = re.compile(
    r"https?://([\w-]+)\.computrabajo\.com/ofertas-de-trabajo/"
    r"(oferta-de-trabajo-de-[\w-]+?)-([0-9A-F]{32})\b",
    re.I,
)
# Indeed job key (16 hex) in a link: /viewjob?jk=..., /rc/clk?jk=..., or inside a redirect.
INDEED_JOB = re.compile(r"[?&](?:jk|vjk)=([0-9a-f]{16})\b", re.I)
ELEMPLEO_JOB = re.compile(
    r"https?://(?:www\.)?elempleo\.com/cr/ofertas-trabajo/([\w-]+)/(\d+)", re.I
)
_ANCHOR = re.compile(r"<a\b[^>]*?href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")
_SEPARATOR = re.compile(r"^[-=_*·•]{5,}$")
# Lines inside an alert that are not title/company/location (EN and ES).
_NOISE = re.compile(
    r"^(view job|ver empleo|ver oferta|ver vacante|ver m[aá]s|apply( now)?|aplicar( ahora)?|"
    r"solicitar|postularme|post[uú]late( ahora| hoy)?|easy apply|"
    r"solicitud sencilla|actively recruiting|contratando activamente|be an early applicant|"
    r"s[eé] de los primeros en solicitar|promoted|promocionado|new|nuevo|"
    r".*\b(connections?|contactos?|alumni|applicants?|solicitantes|school|escuela|"
    r"instituci[oó]n educativa|busca personal activamente|actively hiring|perfil y cv)\b.*)$",
    re.I,
)
# A saved-search alert lists only jobs posted since the previous alert: its "see all" link
# carries f_TPR=a<time of that alert>. Other LinkedIn emails (similar jobs, the suggestions under
# an application confirmation) can bring postings that are months old. So can an alert with no
# new matches, which sends similar jobs instead.
_LINKEDIN_ALERT = re.compile(r"f_TPR=a\d+|\b(your job alert for|tu alerta de empleo para)\b", re.I)
_LINKEDIN_SIMILAR = re.compile(
    r"no hay resultados para tu alerta|empleos similares a tu alerta|"
    r"no (new )?results for your (job )?alert|jobs similar to your alert",
    re.I,
)

Parser = Callable[[MailMessage, str, str], list[Job]]


class MailReader(Protocol):
    def search(self, query: str, max_messages: int) -> list[str]: ...
    def get(self, message_id: str) -> MailMessage: ...


def _clean(fragment: str) -> str:
    text = html_lib.unescape(_TAG.sub(" ", fragment))
    return _SPACES.sub(" ", text).strip()


def _anchors(html: str) -> Iterable[tuple[str, str]]:
    """(decoded href, visible text). Tracking redirects often URL-encode the real target."""
    for href, inner in _ANCHOR.findall(html):
        href = html_lib.unescape(href)
        yield unquote(unquote(href)), _clean(inner)


def _with_country(location: str, country: str) -> str:
    if not country or country.lower() in location.lower():
        return location
    return f"{location}, {country}" if location else country


# --- LinkedIn ---------------------------------------------------------------------------------


def parse_linkedin(message: MailMessage, source: str, default_location: str) -> list[Job]:
    jobs = _linkedin_from_text(message.text) or _linkedin_from_html(message.html)
    body = f"{message.text}\n{message.html}"
    alert = bool(_LINKEDIN_ALERT.search(body)) and not _LINKEDIN_SIMILAR.search(body)
    # LinkedIn's emails carry no posting date: an alert's jobs are about as old as the email.
    posted = message.received_at if alert else None
    return [
        _linkedin_job(job_id, title, company, location or default_location, source).model_copy(
            update={
                "posted_at": posted,
                "posted_approx": posted is not None,
                "recommended": not alert,
            }
        )
        for job_id, (title, company, location) in jobs.items()
    ]


def _linkedin_from_text(text: str) -> dict[str, tuple[str, str, str]]:
    """Blocks of `title / company / location / [insights] / View job: <url>` (plain-text layout).

    Section headings can come before the title ("Tus otros empleos guardados"), so a block is
    read from the end. The insight lines LinkedIn adds after the location now and then
    ("N personas estudiaron…") must be in _NOISE, or they shift the fields.
    """
    jobs: dict[str, tuple[str, str, str]] = {}
    pending: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _SEPARATOR.match(line):
            pending = []
            continue
        match = LINKEDIN_JOB.search(line)
        if not match:
            if not _NOISE.match(line):
                pending.append(line)
            continue
        if pending and match.group(1) not in jobs:
            title, company, location = (pending[-3:] + ["", ""])[:3]
            jobs[match.group(1)] = (title, company, location)
        pending = []
    return jobs


def _linkedin_from_html(html: str) -> dict[str, tuple[str, str, str]]:
    jobs: dict[str, tuple[str, str, str]] = {}
    for href, text in _anchors(html):
        match = LINKEDIN_JOB.search(href)
        if match and text and not _NOISE.match(text) and match.group(1) not in jobs:
            jobs[match.group(1)] = (text, "", "")
    return jobs


def _linkedin_job(job_id: str, title: str, company: str, location: str, source: str) -> Job:
    return Job(
        source=source,
        ats="linkedin",
        ats_job_id=job_id,
        company=company or "(LinkedIn)",
        title=title,
        location=location,
        url=f"https://www.linkedin.com/jobs/view/{job_id}/",
        remote="remote" in location.lower() or "remoto" in location.lower(),
    )


# --- CompuTrabajo -----------------------------------------------------------------------------


def parse_computrabajo(message: MailMessage, source: str, default_location: str) -> list[Job]:
    """Offer links (direct or via go.computrabajo.com redirects) and their card texts."""
    links: dict[str, tuple[re.Match[str], list[str]]] = {}
    for href, text in [*_anchors(message.html), (message.text, "")]:
        for match in COMPUTRABAJO_JOB.finditer(href):
            _, texts = links.setdefault(match.group(3).upper(), (match, []))
            if text and not _NOISE.match(text):
                texts.append(text)
    return [
        _computrabajo_job(job_id, match, texts, source, default_location)
        for job_id, (match, texts) in links.items()
    ]


def _computrabajo_job(
    job_id: str, match: re.Match[str], texts: list[str], source: str, default_location: str
) -> Job:
    host, slug = match.group(1).lower(), match.group(2)
    title_words, location_words = _split_slug(slug)
    title = company = ""
    for text in texts:
        title, company = _card_fields(text, title_words, location_words)
        if title:
            break
    location = " ".join(w.capitalize() for w in location_words) or default_location
    return Job(
        source=source,
        ats="computrabajo",
        ats_job_id=job_id,
        company=company or "(CompuTrabajo)",
        title=title or " ".join(w.capitalize() for w in title_words),
        location=_with_country(location, "Costa Rica" if host == "cr" else ""),
        url=f"https://{host}.computrabajo.com/ofertas-de-trabajo/{slug}-{match.group(3)}",
    )


def _split_slug(slug: str) -> tuple[list[str], list[str]]:
    """'oferta-de-trabajo-de-tecnico-de-soporte-en-heredia' -> (title words, location words)."""
    body = slug.lower().removeprefix("oferta-de-trabajo-de-")
    title, sep, location = body.rpartition("-en-")
    if not sep:
        title, location = body, ""
    return [w for w in title.split("-") if w], [w for w in location.split("-") if w]


_CARD_BADGES = re.compile(
    r"^(?:\s*(?:se precisa urgente|empleo destacado|vacante con alta revisi[oó]n de cvs|"
    r"urgente|nuev[oa])\s*·?)+",
    re.I,
)
_RATING = re.compile(r"^\s*\d[.,]\d\b\s*")


def _fold(text: str) -> str:
    """Lowercase without accents, one output char per input char (positions stay aligned)."""
    return "".join((strip_accents(c) or c)[:1] for c in text).lower()


def _match_title_words(text: str, title_words: list[str], *, glue: bool) -> tuple[int, int]:
    """How many leading slug words the text matches, and where (in `text`) the last one ends."""
    kept = [(c, i) for i, c in enumerate(_fold(text)) if not (glue and c in "()/")]
    folded = "".join(c for c, _ in kept)
    matched, end = 0, 0
    for word in re.finditer(r"\w+", folded):
        if matched < len(title_words) and word.group(0) == title_words[matched]:
            matched, end = matched + 1, kept[word.end() - 1][1] + 1
        else:
            break
    return matched, end


def _card_fields(text: str, title_words: list[str], location_words: list[str]) -> tuple[str, str]:
    """Title and company from a card text: '[badges] Title [4.5] Company City, Province [...]'.

    The URL slug carries the title words, so the card is cut where those words end.
    """
    text = _CARD_BADGES.sub("", text).strip()
    # Slugs write inclusive forms either split ("operario-a") or glued ("operarioa",
    # "administrativoa"): try both readings of ( ) / and keep the longer match.
    matched, end = max(
        _match_title_words(text, title_words, glue=False),
        _match_title_words(text, title_words, glue=True),
    )
    if matched == 0:
        return "", ""
    if text[end : end + 1] == ")":
        end += 1
    rest = _RATING.sub("", text[end:])
    company = ""
    if location_words:
        position = _fold(rest).find(location_words[0])
        if position > 0:
            company = rest[:position].strip(" ,-·")
    return text[:end].strip(), company


# --- Indeed and elempleo ----------------------------------------------------------------------
# Links that carry the job id are trusted first. Opaque tracking links are never resolved:
# that would mean visiting Indeed. Real Indeed alerts (2026-10-29) only have opaque links, so
# their jobs come from the plain-text layout instead (see _indeed_from_text).


def _job_links(message: MailMessage, pattern: re.Pattern[str]) -> dict[str, tuple[str, str]]:
    """{job id: (canonical href match text, best anchor text)} for links matching `pattern`."""
    found: dict[str, tuple[str, str]] = {}
    for href, text in [*_anchors(message.html), (message.text, "")]:
        for match in pattern.finditer(href):
            job_id = match.group(match.lastindex or 0)
            title = text if text and not _NOISE.match(text) and len(text) > 3 else ""
            previous = found.get(job_id)
            if previous is None or (title and not previous[1]):
                found[job_id] = (match.group(0), title)
    return found


def parse_indeed(message: MailMessage, source: str, default_location: str) -> list[Job]:
    keyed = [
        Job(
            source=source,
            ats="indeed",
            ats_job_id=job_key.lower(),
            company="(Indeed)",
            title=title or "(sin título)",
            location=default_location,
            url=f"https://cr.indeed.com/viewjob?jk={job_key.lower()}",
        )
        for job_key, (_, title) in _job_links(message, INDEED_JOB).items()
    ]
    if keyed:
        return keyed
    jobs = []
    for title, company, location, link in _indeed_from_text(message.text):
        location = _with_country(location, default_location)
        # No job key in these emails: the same title/company/place is the same job.
        key = hashlib.sha1(f"{title}|{company}|{location}".lower().encode("utf-8")).hexdigest()
        jobs.append(
            Job(
                source=source,
                ats="indeed",
                ats_job_id=f"mail-{key[:12]}",
                company=company or "(Indeed)",
                title=title,
                location=location,
                url=link,  # Indeed's own click tracker: the candidate opens it, the bot never does
                remote="remot" in location.lower(),
            )
        )
    return jobs


INDEED_TRACKER = re.compile(r"https?://(?:engage|cts)\.indeed\.com/\S+", re.I)
_INDEED_VIEW = re.compile(r"^(?:ver empleo|view job):\s*(https?://\S+)$", re.I)
_BLANK_LINE = re.compile(r"\n\s*\n")


def _indeed_from_text(text: str) -> list[tuple[str, str, str, str]]:
    """(title, company, location, link) from the plain-text part of an Indeed email.

    Daily alerts: blocks of `title / company - location / [badges] / snippet / age / link`.
    Single-job matches: `title / company / location / [Tipo de empleo: …]`, then a block that
    starts with `Ver empleo: link`.
    """
    found: list[tuple[str, str, str, str]] = []
    previous: list[str] = []
    for block in _BLANK_LINE.split(text.replace("\r\n", "\n")):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        link = INDEED_TRACKER.fullmatch(lines[-1])
        view = _INDEED_VIEW.match(lines[0])
        if link and len(lines) >= 3 and " - " in lines[1]:
            company, _, location = lines[1].rpartition(" - ")
            found.append((lines[0], company, location, link.group(0)))
        elif view and len(previous) >= 3:
            found.append((previous[0], previous[1], previous[2], view.group(1)))
        previous = lines
    return found


def parse_elempleo(message: MailMessage, source: str, default_location: str) -> list[Job]:
    jobs = []
    for offer_id, (matched, title) in _job_links(message, ELEMPLEO_JOB).items():
        slug = ELEMPLEO_JOB.search(matched).group(1)
        jobs.append(
            Job(
                source=source,
                ats="elempleo",  # same id space as the direct elempleo source: no duplicates
                ats_job_id=offer_id,
                company="(elempleo)",
                title=title or " ".join(w.capitalize() for w in slug.split("-")),
                location=default_location,
                url=f"https://www.elempleo.com/cr/ofertas-trabajo/{slug}/{offer_id}",
            )
        )
    return jobs


# --- Source -----------------------------------------------------------------------------------

PARSERS: dict[str, Parser] = {
    "linkedin": parse_linkedin,
    "computrabajo": parse_computrabajo,
    "indeed": parse_indeed,
    "elempleo": parse_elempleo,
}


class EmailAlertSource(Source):
    """One source per alert feed (email:linkedin, email:computrabajo)."""

    def __init__(
        self,
        feed: str,
        mail: MailReader,
        query: str,
        *,
        lookback_days: int,
        max_messages: int,
        default_location: str = "",
    ) -> None:
        super().__init__(None)
        self.name = f"email:{feed}"
        self._parser = PARSERS[feed]
        self._mail = mail
        self._query = f"({query}) newer_than:{lookback_days}d"
        self._max_messages = max_messages
        self._default_location = default_location

    def fetch(self) -> Iterable[Job]:
        # The same job shows up in several emails; some only carry a "Postúlate" button.
        best: dict[str, Job] = {}
        for message_id in self._mail.search(self._query, self._max_messages):
            for job in self._parser(self._mail.get(message_id), self.name, self._default_location):
                current = best.get(job.ats_job_id)
                best[job.ats_job_id] = job if current is None else _merge(current, job)
        yield from best.values()


def _merge(current: Job, other: Job) -> Job:
    """One job listed by several emails: the copy with a real company over a "(placeholder)",
    and the date of the earliest saved alert that listed it."""
    keep = current
    if current.company.startswith("(") and not other.company.startswith("("):
        keep = other
    alerts = [j for j in (current, other) if not j.recommended]
    if not alerts:
        return keep
    dates = [j.posted_at for j in alerts if j.posted_at]
    return keep.model_copy(
        update={
            "recommended": False,
            "posted_at": min(dates) if dates else None,
            "posted_approx": any(j.posted_approx for j in alerts),
        }
    )
