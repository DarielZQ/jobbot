"""Hard filters from config/search.yaml. Every rejection carries a reason."""

from __future__ import annotations

import re
from dataclasses import dataclass

from jobbot.config import RoleFamily, SearchRules
from jobbot.core.models import Job
from jobbot.matching.normalize import normalize_text


@dataclass(frozen=True)
class RuleResult:
    ok: bool
    reason: str = ""
    role_family: str = ""


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
        self._location_local = _compile(rules.location.local)
        self._location_local_exclude = _compile(rules.location.local_exclude)
        self._remote_ok = _compile(rules.location.remote_ok)
        self._remote_reject = _compile(rules.location.remote_reject)

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

    def evaluate(self, job: Job) -> RuleResult:
        family = self.classify(job.title)
        if family is None:
            return RuleResult(False, "title_not_target_role")
        if hit := _first_match(self._title_exclude, normalize_text(job.title)):
            return RuleResult(False, f"title_excluded: {hit}", family)

        location_result = self._evaluate_location(job)
        if not location_result.ok:
            return RuleResult(False, location_result.reason, family)

        description = normalize_text(job.description)
        if hit := _first_match(self._description_exclude, description):
            return RuleResult(False, f"description_excluded: {hit}", family)

        return RuleResult(True, role_family=family)

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
            return RuleResult(False, "remote_region_unknown")
        return RuleResult(False, "location_not_target")
