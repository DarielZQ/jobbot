"""ADR-035: one search at a time across processes."""

from __future__ import annotations

from jobbot.core import db, runlock


def test_a_second_search_waits_for_the_first(tmp_path) -> None:
    lock = tmp_path / "jobbot.db.search-lock"
    waits: list[float] = []

    with (
        runlock.exclusive(lock) as first,
        runlock.exclusive(lock, wait_s=0.01, poll_s=0.005, sleep=waits.append) as second,
    ):
        assert first and not second  # it waited, then went ahead
    assert waits

    with runlock.exclusive(lock, wait_s=0) as again:
        assert again  # released when the first search ended


def test_the_lock_sits_next_to_the_database(tmp_path) -> None:
    conn = db.connect(tmp_path / "jobbot.db")
    assert db.lock_path(conn) == tmp_path / "jobbot.db.search-lock"
    assert db.lock_path(db.connect(":memory:")) is None
