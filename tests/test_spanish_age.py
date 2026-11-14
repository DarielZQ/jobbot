"""Spanish postings open to the region, the age limit and the Descartadas list (ADR-023)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from conftest import make_job
from jobbot import daily
from jobbot.core import db
from jobbot.core.state import Status
from jobbot.discovery.pipeline import expire_old, rescreen
from jobbot.discovery.workday import posted_on
from jobbot.panel import apply_action, list_view, summary

NOW = datetime.now(UTC)


def _remote(location: str, title: str = "Analista de Soporte TI", **fields: object):
    return make_job(title=title, location=location, remote=True, **fields)


def _insert(
    conn,
    ats_job_id: str,
    status: Status = Status.DISCOVERED,
    reason: str = "",
    first_seen: datetime | None = None,
    **fields: object,
) -> int:
    job_id = db.insert_job(
        conn,
        make_job(ats_job_id=ats_job_id, **fields),
        dedupe_key=ats_job_id,
        status=status,
        status_reason=reason,
        role_family="it_support",
    )
    if first_seen:
        conn.execute(
            "UPDATE jobs SET first_seen_at = ? WHERE id = ?",
            (first_seen.isoformat(timespec="seconds"), job_id),
        )
    return job_id


# --- Spanish postings -----------------------------------------------------------------------


def test_spanish_region_words_count_as_eligible_remote(rules) -> None:
    for location in ("Remoto - Latinoamérica", "Remoto (América Latina)", "Remoto, cualquier país"):
        assert rules.evaluate(_remote(location)).ok, location


def test_a_spanish_posting_that_only_says_remoto_passes_with_a_note(rules) -> None:
    spanish = rules.evaluate(_remote("Remoto", description="Buscamos analista para la mesa."))
    english = rules.evaluate(_remote("Remote", title="IT Support Analyst"))

    assert spanish.ok and spanish.reason == "remote_no_country"
    assert not english.ok and english.reason == "remote_region_unknown"
    row = db.JobRow(
        id=1,
        source="s",
        company="Acme",
        title="t",
        location="Remoto",
        url="u",
        status=Status.DISCOVERED,
        status_reason="remote_no_country",
        role_family="it_support",
        first_seen_at=NOW.isoformat(),
    )
    assert daily.job_notes(row, "Costa Rica") == [
        "Remoto sin país: confirma que acepten Costa Rica"
    ]


# --- Age limit ------------------------------------------------------------------------------


def test_postings_older_than_the_limit_are_discarded_on_arrival(rules) -> None:
    old = rules.evaluate(make_job(posted_at=NOW - timedelta(days=40)))
    recent = rules.evaluate(make_job(posted_at=NOW - timedelta(days=10)))
    workday = rules.evaluate(make_job(posted_at=posted_on("Posted 30+ Days Ago", NOW)))

    assert not old.ok and old.reason == "too_old: 40 días"
    assert recent.ok
    assert not workday.ok  # "30+" is past a 30-day limit


def test_pending_jobs_that_grow_too_old_go_to_descartadas(conn, rules) -> None:
    dated = _insert(conn, "dated", posted_at=NOW - timedelta(days=35))
    undated = _insert(conn, "undated", first_seen=NOW - timedelta(days=31))
    kept = _insert(
        conn,
        "kept",
        status=Status.DISCOVERED,
        reason=db.REOPENED_MANUALLY,
        posted_at=NOW - timedelta(days=60),
    )
    recent = _insert(conn, "recent", posted_at=NOW - timedelta(days=2))

    assert expire_old(conn, rules) == 2

    status = {r.id: (r.status, r.status_reason) for r in db.list_jobs(conn, limit=10)}
    assert status[dated] == (Status.SKIPPED, "too_old: 35 días")
    assert status[undated] == (Status.SKIPPED, "too_old: 31 días")
    assert status[kept][0] is Status.DISCOVERED and status[recent][0] is Status.DISCOVERED


def test_rescreen_keeps_an_undated_old_job_discarded(conn, rules) -> None:
    _insert(
        conn,
        "old",
        status=Status.SKIPPED,
        reason="too_old: 31 días",
        first_seen=NOW - timedelta(days=31),
    )

    assert rescreen(conn, rules)["reopened"] == 0


# --- Descartadas ----------------------------------------------------------------------------


def test_descartadas_lists_only_recent_jobs_not_taken_off(conn) -> None:
    shown = _insert(
        conn,
        "shown",
        status=Status.SKIPPED,
        reason="title_excluded: senior",
        title="Senior Help Desk",
        posted_at=NOW - timedelta(days=3),
    )
    hidden = _insert(
        conn,
        "hidden",
        status=Status.SKIPPED,
        reason="title_not_target_role",
        title="Accountant",
        posted_at=NOW - timedelta(days=1),
    )
    _insert(
        conn,
        "old",
        status=Status.SKIPPED,
        reason="title_not_target_role",
        title="Old one",
        posted_at=NOW - timedelta(days=45),
    )

    apply_action(conn, hidden, "hide")

    assert [j["id"] for j in list_view(conn, "skipped")] == [shown]
    assert summary(conn)["counts"]["skipped"] == 1
    apply_action(conn, hidden, "unhide")  # Deshacer
    assert {j["id"] for j in list_view(conn, "skipped")} == {shown, hidden}


def test_jobs_carry_language_and_a_sortable_date(conn) -> None:
    _insert(conn, "es", title="Analista de Soporte TI", posted_at=NOW - timedelta(days=1))
    _insert(conn, "en", title="IT Support Analyst", ats="t2")

    jobs = {j["title"]: j for j in list_view(conn, "pending")}

    assert jobs["Analista de Soporte TI"]["lang"] == "es"
    assert jobs["IT Support Analyst"]["lang"] == "en"
    assert jobs["IT Support Analyst"]["posted_at"]  # first seen when the date is unknown


# --- LinkedIn -------------------------------------------------------------------------------


def test_linkedin_has_a_remote_latin_america_group() -> None:
    groups = {group.label: group.links for group in daily.linkedin_links()}
    keywords, url = groups["Latinoamérica remoto"][0]
    query = parse_qs(urlparse(url).query)

    assert keywords == "soporte técnico"
    assert query["location"] == ["Latinoamérica"] and query["f_WT"] == ["2"]
    assert "geoId" not in query
