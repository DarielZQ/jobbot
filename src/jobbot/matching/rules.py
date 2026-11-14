"""Hard filters from config/search.yaml. Every rejection carries a reason."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from jobbot.config import RoleFamily, SearchRules
from jobbot.core.models import Job, as_utc, posted_within
from jobbot.matching.language import detect_language
from jobbot.matching.normalize import normalize_text

# Notes on a job that passes, so the panel can say why (joined with NOTE_SEPARATOR):
# a fresh posting a board's seniority label would have excluded (ADR-020), and a Spanish posting
# that only says "Remoto" (ADR-023).
FRESH_SENIORITY = "fresh_seniority"
REMOTE_NO_COUNTRY = "remote_no_country"
# The description asks for current enrollment: someone who finished their studies should check
# before applying (ADR-024).
ENROLLMENT_REQUIRED = "enrollment_required"
NOTE_SEPARATOR = "; "
# On normalized text. "current students and recent graduates" also takes graduates: no note.
_ENROLLMENT = re.compile(
    r"\b(?:currently enrolled|must be (?:currently )?enrolled|be enrolled in"
    r"|enrolled (?:full[ -]time )?in an? (?:accredited )?(?:bachelor|degree|university|college"
    r"|undergraduate)"
    r"|(?:active|current|full[ -]time) (?:university |college )?students?(?! (?:and|or) recent)"
    r"|currently pursuing(?! or (?:have )?recently)"
    r"|estudiantes? (?:activ[oa]s?|regular(?:es)?)|matriculad[oa]s?|empadronad[oa]s?"
    r"|(?:estar|encontrarse|actualmente) cursando)\b"
)
# First-job titles: internships, trainee and graduate programs, junior roles (ADR-024)
_ENTRY_LEVEL = re.compile(
    r"\b(?:interns?|internship|co[ -]?op|trainee|apprentice(?:ship)?|pasante|pasantia"
    r"|practicante|practica profesional|becari[oa]|junior|jr|entry[ -]level|new[ -]grad(?:uate)?"
    r"|graduate (?:program|programme|scheme|trainee|analyst|engineer|developer)"
    r"|early[ -]career|recien graduad[oa]|egresad[oa])\b"
)
# Posted (or, without a date, first seen) more than `max_age_days` ago (ADR-023)
TOO_OLD = "too_old"
# "Remoto", "100% remoto", "Remote": remote with no place at all
_BARE_REMOTE = re.compile(
    r"^(?:100 |fully |full |trabajo |)?(?:remote|remoto|teletrabajo)(?: work| total| 100)?$"
)


@dataclass(frozen=True)
class RuleResult:
    ok: bool
    reason: str = ""  # why it was excluded; for one that passes, its notes
    role_family: str = ""


def entry_level(title: str) -> bool:
    """An internship, trainee or graduate program, or a junior role: the panel's "Entrada"."""
    return _ENTRY_LEVEL.search(normalize_text(title)) is not None


def _compile(patterns: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(p) for p in patterns]


def _first_match(patterns: list[re.Pattern[str]], text: str) -> str | None:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


@dataclass(frozen=True)
class _CompiledFamily:
    name: str
    include: list[re.Pattern[str]]
    exclude: list[re.Pattern[str]]


def _compile_family(name: str, family: RoleFamily) -> _CompiledFamily:
    return _CompiledFamily(name, _compile(family.include), _compile(family.exclude))


class RuleSet:
    def __init__(self, rules: SearchRules) -> None:
        # Primary families are tried first; dict order breaks ties.
        ordered = sorted(
            rules.role_families.items(), key=lambda item: item[1].priority != "primary"
        )
        self._families = [_compile_family(name, family) for name, family in ordered]
        self._title_exclude = _compile(rules.title.exclude)
        self._description_exclude = _compile(rules.description.exclude)
        self._description_seniority = _compile(rules.description.seniority)
        self.fresh_hours = rules.fresh_hours
        self.max_age_days = rules.max_age_days
        self._location_local = _compile(rules.location.local)
        self._location_local_exclude = _compile(rules.location.local_exclude)
        self._remote_ok = _compile(rules.location.remote_ok)
        self._remote_reject = _compile(rules.location.remote_reject)
        self._any_role = {normalize_text(c) for c in rules.any_role_companies}

    def classify(self, title: str) -> str | None:
        """Name of the first role family whose include matches and exclude does not."""
        normalized = normalize_text(title)
        for family in self._families:
            if _first_match(family.include, normalized) and not _first_match(
                family.exclude, normalized
            ):
                return family.name
        return None

    def in_local_area(self, location: str) -> bool:
        return _first_match(self._location_local, normalize_text(location)) is not None

    def age_days(self, posted_at: datetime | None, first_seen: datetime | None = None) -> int:
        """Days since it was posted or, without a date, since it was first seen (0 if neither)."""
        moment = posted_at or first_seen
        return (datetime.now(UTC) - as_utc(moment)).days if moment else 0

    def too_old(self, posted_at: datetime | None, first_seen: datetime | None = None) -> bool:
        """Older than `max_age_days` today (no limit when it is 0)."""
        moment = posted_at or first_seen
        if not self.max_age_days or moment is None:
            return False
        return (datetime.now(UTC) - as_utc(moment)).total_seconds() > self.max_age_days * 86400

    def evaluate(self, job: Job, seen_at: datetime | None = None) -> RuleResult:
        """`seen_at`: when the job was first seen (now, unless given); freshness counts from it.
        Age always counts until today: a posting that grew too old is excluded on a rescreen."""
        family = self.classify(job.title)
        if family is None:
            if normalize_text(job.company) not in self._any_role:
                return RuleResult(False, "title_not_target_role")
            family = ""  # any_role_companies: no family; the report lists it under "Otras"
        if hit := _first_match(self._title_exclude, normalize_text(job.title)):
            return RuleResult(False, f"title_excluded: {hit}", family)
        if self.too_old(job.posted_at):
            return RuleResult(False, f"{TOO_OLD}: {self.age_days(job.posted_at)} días", family)

        location_result = self._evaluate_location(job)
        if not location_result.ok:
            return RuleResult(False, location_result.reason, family)
        notes = [location_result.reason] if location_result.reason else []

        description = normalize_text(job.description)
        if hit := _first_match(self._description_exclude, description):
            return RuleResult(False, f"description_excluded: {hit}", family)
        if hit := _first_match(self._description_seniority, description):
            if not posted_within(job.posted_at, self.fresh_hours, seen_at):
                return RuleResult(False, f"description_excluded: {hit}", family)
            notes.append(f"{FRESH_SENIORITY}: {hit}")
        if enrollment := _ENROLLMENT.search(description):
            notes.append(f"{ENROLLMENT_REQUIRED}: {enrollment.group(0)}")

        return RuleResult(True, NOTE_SEPARATOR.join(notes), family)

    def _evaluate_location(self, job: Job) -> RuleResult:
        location = normalize_text(job.location)
        if _first_match(self._location_local, location):
            # Some boards put the office city in the location and the real site in the title:
            # "Técnico de soporte regional N1 (<ciudad>)" listed under the capital.
            place = f"{location} {normalize_text(job.title)}"
            if hit := _first_match(self._location_local_exclude, place):
                return RuleResult(False, f"location_outside_area: {hit}")
            return RuleResult(True)
        if hit := _first_match(self._remote_reject, location):
            return RuleResult(False, f"remote_not_eligible: {hit}")
        if job.remote or "remote" in location or "remoto" in location:
            if _first_match(self._remote_ok, location):
                return RuleResult(True)
            # A Spanish posting that only says "Remoto" is often open to the whole region: it
            # passes with a note to check the country (ADR-023). An English one does not.
            bare = not location or _BARE_REMOTE.match(location)
            if bare and detect_language(job.title, job.description) == "es":
                return RuleResult(True, REMOTE_NO_COUNTRY)
            return RuleResult(False, "remote_region_unknown")
        return RuleResult(False, "location_not_target")
