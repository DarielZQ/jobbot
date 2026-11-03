"""Grill-me (ADR-019): JobBot asks instead of assuming.

Two modes, both deterministic (no language model):
- Topics (`jobbot grill <tema>`): an interview in rounds. A round is every question whose
  prerequisites are answered; each has short options and, for preferences only, a recommended
  answer with its reason. Facts about the user are never recommended nor invented.
- Decisions (`jobbot grill pendientes`, panel tab "Decisiones"): questions that the daily run
  queues from what it sees in the database (grill/signals.py).

Nothing is written before the user sees the exact change and confirms it (grill/apply.py).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import yaml

from jobbot import paths

GRILL_DIR = paths.TEMPLATES_DIR / "grill"
LETTERS = "abcdefghij"


@dataclass(frozen=True)
class Question:
    id: str
    ask: str
    options: tuple[str, ...] = ()
    text: bool = False  # free answer instead of options
    optional: bool = False  # a free answer may stay empty
    other: str = ""  # the option that asks for a free answer ("Otro")
    recommended: str = ""
    reason: str = ""
    depends_on: tuple[str, ...] = ()
    when: dict[str, str] = field(default_factory=dict)
    apply: str = ""


@dataclass(frozen=True)
class Topic:
    name: str
    title: str
    intro: str
    questions: tuple[Question, ...]


def topics() -> list[str]:
    return sorted(
        p.stem
        for p in GRILL_DIR.glob("*.yaml")
        if "questions" in (yaml.safe_load(p.read_text(encoding="utf-8")) or {})
    )


def load_topic(name: str) -> Topic:
    data = yaml.safe_load((GRILL_DIR / f"{name}.yaml").read_text(encoding="utf-8"))
    questions = tuple(
        Question(
            **{
                **q,
                "options": tuple(q.get("options") or ()),
                "depends_on": tuple(q.get("depends_on") or ()),
                "when": dict(q.get("when") or {}),
            }
        )
        for q in data["questions"]
    )
    return Topic(name, data.get("title", name), data.get("intro", ""), questions)


def frontier(questions: tuple[Question, ...], answers: dict[str, str]) -> list[Question]:
    """Open questions whose prerequisites are answered and whose `when` holds.

    A question whose `when` turned out false is never asked; the interview ends when no open
    question can be asked any more.
    """
    return [
        q
        for q in questions
        if q.id not in answers
        and all(d in answers for d in q.depends_on)
        and all(answers.get(key) == value for key, value in q.when.items())
    ]


def render(question: Question, number: int) -> str:
    lines = [f"❓ Q{number} - {question.ask}"]
    if question.options:
        lines += [f"   {LETTERS[i]}) {option}" for i, option in enumerate(question.options)]
    else:
        lines.append("   (respuesta libre)")
    if question.recommended:
        reason = f": {question.reason}" if question.reason else ""
        lines.append(f"   ➡️ Recomendada: {question.recommended}{reason}")
    return "\n".join(lines)


def parse(question: Question, raw: str) -> str | None:
    """The answer for a raw reply, or None when it is not valid (ask again)."""
    raw = raw.strip()
    if not raw:
        if question.recommended:
            return question.recommended
        return "" if question.optional else None
    if question.text:
        return raw
    if len(raw) == 1 and raw.lower() in LETTERS[: len(question.options)]:
        return question.options[LETTERS.index(raw.lower())]
    matches = [o for o in question.options if o.lower() == raw.lower()]
    return matches[0] if matches else None


def interview(
    topic: Topic, ask: Callable[[str], str] = input, out: Callable[[str], None] = print
) -> dict[str, str]:
    """Ask round after round until no question is left. Returns {question id: answer}."""
    answers: dict[str, str] = {}
    out(f"{topic.title}\n{topic.intro}")
    number = 0
    while batch := frontier(topic.questions, answers):
        out(f"\nRonda de {len(batch)} pregunta{'s' if len(batch) > 1 else ''}:\n")
        out("\n\n".join(render(q, number + i) for i, q in enumerate(batch, 1)))
        for i, question in enumerate(batch, 1):
            answers[question.id] = _ask(question, number + i, ask, out)
        number += len(batch)
    return answers


def _ask(question: Question, number: int, ask: Callable[[str], str], out) -> str:
    while (answer := parse(question, ask(f"\nQ{number}: "))) is None:
        out("   Respuesta no válida: elige una letra de las opciones o escribe tu respuesta.")
    if question.other and answer == question.other:
        while not (answer := ask(f"Q{number}, ¿cuál?: ").strip()):
            pass
    return answer
