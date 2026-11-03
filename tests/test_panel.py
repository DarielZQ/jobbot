"""Local panel (ADR-016): request guard, views and actions, without starting a server."""

from __future__ import annotations

import pytest

from conftest import make_job
from jobbot import panel
from jobbot.core import db
from jobbot.core.state import InvalidTransition, Status

PORT = 8765
ORIGIN = f"http://127.0.0.1:{PORT}"


@pytest.mark.parametrize(
    ("host", "origin", "content_type", "write", "ok"),
    [
        (f"127.0.0.1:{PORT}", None, None, False, True),
        (f"localhost:{PORT}", None, None, False, True),
        ("evil.example:8765", None, None, False, False),  # DNS rebinding
        (f"127.0.0.1:{PORT}", ORIGIN, "application/json", True, True),
        (f"127.0.0.1:{PORT}", "https://evil.example", "application/json", True, False),
        (f"127.0.0.1:{PORT}", None, "application/json", True, False),  # no Origin
        (f"127.0.0.1:{PORT}", ORIGIN, "text/plain", True, False),  # form-style CSRF
    ],
)
def test_request_allowed(host, origin, content_type, write, ok) -> None:
    assert panel.request_allowed(host, origin, content_type, PORT, write=write) is ok


def _add(conn, n: int, status: Status = Status.DISCOVERED, reason: str = "", **job) -> int:
    return db.insert_job(
        conn,
        make_job(ats_job_id=str(n), **job),
        dedupe_key=str(n),
        status=status,
        status_reason=reason,
        role_family="it_support",
    )


def test_views_counts_and_cv(conn) -> None:
    pending = _add(conn, 1, title="Soporte técnico")
    _add(conn, 2, Status.SKIPPED, "title_not_target_role", title="Contador")
    applied = _add(conn, 3, title="Help Desk")
    db.mark_applied(conn, applied)

    jobs = panel.list_view(conn, "pending")
    assert [j["id"] for j in jobs] == [pending]
    assert jobs[0]["new"] is True and jobs[0]["cv"]["file"] == "it-support_es.pdf"
    assert panel.list_view(conn, "skipped")[0]["cv"] is None  # no CV advice for discarded

    data = panel.summary(conn)
    counts = {"pending": 1, "applied": 1, "interview": 0, "closed": 0, "skipped": 1}
    assert data["counts"] == {**counts, "decisions": 0}
    assert data["new"] == 1 and data["last_search"]
    assert data["families"] == {"it_support": "Soporte TI", "data_ai": "Datos / IA"}


def test_jobs_say_whether_they_are_remote_national_or_abroad(conn) -> None:
    _add(conn, 1, title="Help Desk", location="Remote - LATAM", remote=True)
    _add(conn, 2, title="Service Desk Analyst", location="Heredia (hybrid)")
    _add(conn, 3, Status.SKIPPED, "location_not_target", title="Soporte TI", location="Chile")

    pending = {j["title"]: j["place"] for j in panel.list_view(conn, "pending")}
    assert pending == {"Help Desk": "remote", "Service Desk Analyst": "national"}
    assert panel.list_view(conn, "skipped")[0]["place"] == "abroad"


def test_pending_job_already_applied_elsewhere_is_flagged(conn) -> None:
    applied = _add(
        conn, 1, title="Técnicos(as) de Soporte", company="Globex S.A.", location="Curridabat"
    )
    db.mark_applied(conn, applied)
    twin = _add(conn, 2, title="Técnicos(as) de Soporte", company="GLOBEX", location="San Pedro")
    other = _add(conn, 3, title="Help Desk", company="Globex S.A.")

    flags = {j["id"]: j["twin"] for j in panel.list_view(conn, "pending")}
    expected = {"id": applied, "title": "Técnicos(as) de Soporte", "company": "Globex S.A."}
    assert flags[twin] == expected
    assert flags[other] is None


def test_actions_follow_the_job_lifecycle(conn) -> None:
    job_id = _add(conn, 1)

    assert panel.apply_action(conn, job_id, "applied")["status"] == "submitted"
    assert panel.apply_action(conn, job_id, "interview")["status"] == "interview"
    assert panel.apply_action(conn, job_id, "rejected")["status"] == "rejected"
    with pytest.raises(InvalidTransition):
        panel.apply_action(conn, job_id, "applied")
    with pytest.raises(ValueError):
        panel.apply_action(conn, job_id, "delete")
    with pytest.raises(KeyError):
        panel.apply_action(conn, 999, "applied")


def test_not_interested_survives_rescreen_and_can_be_reopened(conn, rules) -> None:
    from jobbot.discovery.pipeline import rescreen

    job_id = _add(conn, 1, title="Help Desk Technician")
    panel.apply_action(conn, job_id, "not_interested")
    rescreen(conn, rules)  # the job passes the filters, but the candidate said no
    assert db.get_job(conn, job_id).status_reason == db.NOT_INTERESTED

    assert panel.apply_action(conn, job_id, "reopen")["status"] == "discovered"
    rescreen(conn, rules)
    assert db.get_job(conn, job_id).status_reason == db.REOPENED_MANUALLY


def test_reopen_refuses_duplicates(conn) -> None:
    job_id = _add(conn, 1, Status.SKIPPED, "duplicate_of: 7")
    with pytest.raises(InvalidTransition):
        panel.apply_action(conn, job_id, "reopen")


def test_page_and_icon_ship_with_the_package() -> None:
    page = (panel.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "/api/summary" in page and "Ya postulé" in page
    assert ".innerHTML" not in page  # job data from the web is inserted as text only
    assert (panel.STATIC_DIR / "jobbot.ico").read_bytes()[:4] == b"\x00\x00\x01\x00"
