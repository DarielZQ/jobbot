"""Job lifecycle states and allowed transitions (see docs/architecture.md)."""

from __future__ import annotations

from enum import StrEnum


class Status(StrEnum):
    DISCOVERED = "discovered"
    SKIPPED = "skipped"
    SCORED = "scored"
    QUEUED = "queued"
    APPLYING = "applying"
    SUBMITTED = "submitted"
    NEEDS_INPUT = "needs_input"
    BLOCKED_CHALLENGE = "blocked_challenge"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    INTERVIEW = "interview"


TRANSITIONS: dict[Status, frozenset[Status]] = {
    # SUBMITTED from the early states = the candidate applied by hand (`jobbot applied`).
    Status.DISCOVERED: frozenset({Status.SKIPPED, Status.SCORED, Status.SUBMITTED}),
    Status.SCORED: frozenset({Status.QUEUED, Status.SKIPPED, Status.SUBMITTED}),
    Status.QUEUED: frozenset({Status.APPLYING, Status.SKIPPED, Status.SUBMITTED}),
    Status.APPLYING: frozenset(
        {
            Status.SUBMITTED,
            Status.NEEDS_INPUT,
            Status.BLOCKED_CHALLENGE,
            Status.FAILED,
            Status.UNCERTAIN,
        }
    ),
    Status.NEEDS_INPUT: frozenset({Status.QUEUED, Status.SKIPPED}),
    Status.BLOCKED_CHALLENGE: frozenset({Status.QUEUED, Status.SKIPPED}),
    Status.FAILED: frozenset({Status.QUEUED, Status.SKIPPED}),
    # DISCOVERED: undo of a manual mark (`jobbot applied --undo`).
    Status.SUBMITTED: frozenset(
        {Status.CONFIRMED, Status.REJECTED, Status.INTERVIEW, Status.DISCOVERED}
    ),
    Status.CONFIRMED: frozenset({Status.REJECTED, Status.INTERVIEW}),
    Status.INTERVIEW: frozenset({Status.REJECTED}),
    # UNCERTAIN only leaves via manual reconciliation; never retried automatically.
    Status.UNCERTAIN: frozenset({Status.CONFIRMED, Status.REJECTED, Status.INTERVIEW}),
    # `jobbot rescreen` reopens a skipped job after the filters change; the candidate may also
    # have applied by hand to something the filters skipped.
    Status.SKIPPED: frozenset({Status.DISCOVERED, Status.SUBMITTED}),
    Status.REJECTED: frozenset(),
}


class InvalidTransition(ValueError):
    pass


def check_transition(current: Status, new: Status) -> None:
    if new not in TRANSITIONS[current]:
        raise InvalidTransition(f"{current.value} -> {new.value} is not allowed")
