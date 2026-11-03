"""Turn grill-me answers into changes to the user's YAML files, keeping their comments.

`plan(answers)` only computes the changes; the caller shows `Plan.changes` and calls
`Plan.save()` after the user confirms.
"""

from __future__ import annotations

from collections.abc import Callable
from io import StringIO
from pathlib import Path

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from jobbot import paths
from jobbot.grill import GRILL_DIR
from jobbot.matching.normalize import normalize_text

SETTINGS = "config/settings.yaml"
SEARCH = "config/search.yaml"
FACTS = "profile/facts.yaml"
CONTACT = "profile/private/contact.yaml"

# Title patterns for "Solo nivel 1": level 2 in its usual spellings, but not mixed "Level 1/2".
LEVEL_2 = [
    r"\b(ii|tier\s*(2|ii)|level\s*(2|ii)|nivel\s*(2|ii)"
    r"|(2nd|second)\s+(level|line|tier)|segundo\s+nivel)\b",
    r"(?<!l1 )(?<!n1 )\b(l2|n2)\b",
    r"\bmid\b(?![\s-]*market)",
    r"\b(semi\s*-?\s*senior|ssr|intermediate|intermedio)\b",
]
LEVEL_3 = r"\b(iii|iv|level\s*3|l3|nivel\s*3)\b"
FAMILIES = {
    "Soporte TI": ["it_support"],
    "Soporte TI y datos": ["it_support", "data_ai"],
    "Solo datos": ["data_ai"],
}


class Plan:
    def __init__(self, home: Path | None = None) -> None:
        self.home = home or paths.home()
        self.changes: list[str] = []
        self._docs: dict[str, CommentedMap] = {}
        self._yaml = YAML()
        self._yaml.preserve_quotes = True
        self._yaml.width = 4096  # never re-wrap long regex lines

    def doc(self, rel: str) -> CommentedMap:
        if rel not in self._docs:
            path = self.home / rel
            text = path.read_text(encoding="utf-8") if path.exists() else ""
            self._docs[rel] = self._yaml.load(text) or CommentedMap()
        return self._docs[rel]

    def _parent(self, rel: str, keys: tuple[str, ...]) -> CommentedMap:
        node = self.doc(rel)
        for key in keys[:-1]:
            if not isinstance(node.get(key), dict):
                node[key] = CommentedMap()
            node = node[key]
        return node

    def set(self, rel: str, keys: tuple[str, ...], value: object) -> None:
        parent = self._parent(rel, keys)
        if parent.get(keys[-1]) != value:
            parent[keys[-1]] = value
            self.changes.append(f"{rel}: {'.'.join(keys)} = {value!r}")

    def delete(self, rel: str, keys: tuple[str, ...]) -> None:
        parent = self._parent(rel, keys)
        if keys[-1] in parent:
            del parent[keys[-1]]
            self.changes.append(f"{rel}: se quita {'.'.join(keys)}")

    def edit_list(self, rel: str, keys: tuple[str, ...], fn: Callable[[list], list]) -> None:
        parent = self._parent(rel, keys)
        current = list(parent.get(keys[-1]) or [])
        updated = fn(list(current))
        if updated != current:
            parent[keys[-1]] = updated
            added = [x for x in updated if x not in current]
            removed = [x for x in current if x not in updated]
            for item in added:
                self.changes.append(f"{rel}: {'.'.join(keys)} + {item!r}")
            for item in removed:
                self.changes.append(f"{rel}: {'.'.join(keys)} - {item!r}")

    def save(self) -> list[Path]:
        saved = []
        for rel, doc in self._docs.items():
            path = self.home / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            buffer = StringIO()
            self._yaml.dump(doc, buffer)
            path.write_text(buffer.getvalue(), encoding="utf-8")
            saved.append(path)
        return saved


def countries() -> dict[str, dict]:
    return yaml.safe_load((GRILL_DIR / "countries.yaml").read_text(encoding="utf-8"))


def _country(plan: Plan, answer: str, answers: dict[str, str]) -> None:
    known = countries().get(answer)
    country = (known or {}).get("country", answer)
    plan.set(SETTINGS, ("region", "country"), country)
    for key in ("country_code", "country_slug", "utc_offset", "timezone"):
        if known and key in known:
            plan.set(SETTINGS, ("region", key), known[key])
    plan.set(FACTS, ("identity", "location", "country"), answer)


def _families(plan: Plan, answer: str, answers: dict[str, str]) -> None:
    keep = FAMILIES[answer]
    for name in list(plan.doc(SEARCH).get("role_families") or {}):
        if name not in keep:
            plan.delete(SEARCH, ("role_families", name))
    plan.set(SEARCH, ("role_families", keep[0], "priority"), "primary")


def _max_level(plan: Plan, answer: str, answers: dict[str, str]) -> None:
    def update(patterns: list) -> list:
        if answer == "Solo nivel 1":
            patterns += [p for p in LEVEL_2 if p not in patterns]
        elif answer == "Cualquiera salvo senior":
            patterns = [p for p in patterns if p != LEVEL_3]
        return patterns

    plan.edit_list(SEARCH, ("title", "exclude"), update)


def _modality(plan: Plan, answer: str, answers: dict[str, str]) -> None:
    if answer == "Solo remoto":
        plan.set(SEARCH, ("location", "local"), [])
        plan.set(SEARCH, ("location", "local_exclude"), [])


def _local_area(plan: Plan, answer: str, answers: dict[str, str]) -> None:
    places = [normalize_text(p) for p in answer.split(",") if normalize_text(p)]
    if places:
        pattern = r"\b(" + "|".join(places) + r")\b"
        plan.edit_list(SEARCH, ("location", "local"), lambda items: [*items, pattern])


def _languages(plan: Plan, answer: str, answers: dict[str, str]) -> None:
    if "portugués" not in answer:
        return

    def speak_portuguese(patterns: list) -> list:
        return [p.replace("|portuguese", "").replace("|portugues", "") for p in patterns]

    plan.edit_list(SEARCH, ("title", "exclude"), speak_portuguese)


def _contact_field(rel: str, keys: tuple[str, ...]) -> Callable[[Plan, str, dict], None]:
    def apply(plan: Plan, answer: str, answers: dict[str, str]) -> None:
        if answer:
            plan.set(rel, keys, answer)

    return apply


APPLIERS: dict[str, Callable[[Plan, str, dict[str, str]], None]] = {
    "country": _country,
    "families": _families,
    "max_level": _max_level,
    "modality": _modality,
    "local_area": _local_area,
    "languages": _languages,
    "name": _contact_field(FACTS, ("identity", "name")),
    "email": _contact_field(CONTACT, ("email",)),
    "phone": _contact_field(CONTACT, ("phone",)),
}


def plan(answers: dict[str, str], questions, home: Path | None = None) -> Plan:
    """Changes for the answers of a topic (in question order); nothing is written yet."""
    result = Plan(home)
    for question in questions:
        if question.id in answers and question.apply:
            APPLIERS[question.apply](result, answers[question.id], answers)
    return result
