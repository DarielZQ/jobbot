"""Daily run: new-match query, HTML report and notification text (no toast is shown in tests)."""

from __future__ import annotations

from datetime import datetime

from conftest import make_job
from jobbot import daily
from jobbot.config import load_search_rules
from jobbot.core import db
from jobbot.core.state import Status
from jobbot.discovery.pipeline import SourceReport


def _rows(conn) -> list[db.JobRow]:
    return db.list_jobs(conn, status=Status.DISCOVERED)


def test_new_matches_since_only_returns_recent_discovered(conn) -> None:
    old = make_job(ats_job_id="old", title="Service Desk Analyst")
    db.insert_job(conn, old, dedupe_key="k1", status=Status.DISCOVERED, role_family="it_support")
    conn.execute("UPDATE jobs SET first_seen_at = '2026-01-01T00:00:00+00:00'")
    since = db.utc_now()
    new = make_job(ats_job_id="new", title="Help Desk Technician", company="Acme")
    db.insert_job(conn, new, dedupe_key="k2", status=Status.DISCOVERED, role_family="it_support")
    skipped = make_job(ats_job_id="skip", title="Senior Help Desk")
    db.insert_job(conn, skipped, dedupe_key="k3", status=Status.SKIPPED, status_reason="x")

    assert [r.title for r in db.new_matches_since(conn, since)] == ["Help Desk Technician"]


def test_report_groups_by_family_escapes_html_and_lists_issues(conn, tmp_path) -> None:
    db.insert_job(
        conn,
        make_job(ats_job_id="1", title="Soporte <TI>", company="A&B", url="https://x.cr/1"),
        dedupe_key="a",
        status=Status.DISCOVERED,
        role_family="it_support",
    )
    db.insert_job(
        conn,
        make_job(ats_job_id="2", title="Data Analyst", company="Beta"),
        dedupe_key="b",
        status=Status.DISCOVERED,
        role_family="data_ai",
    )
    results = [
        ("workday:intel", SourceReport(new_matched=1)),
        ("email:linkedin", SourceReport(not_configured="token de Gmail vencido")),
    ]
    path = daily.write_report(
        conn, load_search_rules(), _rows(conn), results, tmp_path, now=datetime(2026, 10, 28, 7)
    )

    page = path.read_text(encoding="utf-8")
    assert path.name == "latest.html" and (tmp_path / "2026-10-28.html").exists()
    assert "Vacantes nuevas: 2" in page
    assert "Soporte TI (1)" in page and "Datos / IA (1)" in page
    assert "Soporte &lt;TI&gt;" in page and "A&amp;B" in page  # escaped
    assert "it-support_es.pdf" in page and "data-ai_en.pdf" in page  # CV per job
    assert "Necesita tu atención" in page and "token de Gmail vencido" in page
    assert "1 fuentes revisadas" in page  # the unconfigured source is not counted
    assert "Pendientes de postular" not in page  # both jobs are new


def test_offline_report_lists_older_pending_and_skips_dated_copy(conn, tmp_path) -> None:
    for i, title in enumerate(["Help Desk Technician", "Soporte técnico", "Service Desk"]):
        db.insert_job(
            conn,
            make_job(ats_job_id=str(i), title=title),
            dedupe_key=str(i),
            status=Status.DISCOVERED,
            role_family="it_support",
        )
    newest, older, applied = _rows(conn)
    db.mark_applied(conn, applied.id)

    path = daily.write_report(conn, load_search_rules(), [newest], [], tmp_path)

    page = path.read_text(encoding="utf-8")
    assert list(tmp_path.iterdir()) == [path]  # no dated copy without a real run
    assert "regenerado sin consultar fuentes" in page
    assert "Pendientes de postular de días anteriores (1)" in page
    assert "2 pendientes de postular · 1 postuladas" in page
    assert older.title in page and applied.title not in page


def test_report_flags_jobs_already_applied_elsewhere(conn, tmp_path) -> None:
    for i, location in enumerate(["Remote - Anywhere", "Remote - Worldwide"]):
        job = make_job(
            ats_job_id=str(i),
            title="Cloud Support Engineer",
            company="Nimbus Cloud",
            location=location,
        )
        db.insert_job(
            conn,
            job,
            dedupe_key=str(i),
            status=Status.DISCOVERED,
            role_family="it_support",
        )
    pending, applied = _rows(conn)
    db.mark_applied(conn, applied.id)

    page = daily.write_report(conn, load_search_rules(), [pending], [], tmp_path).read_text(
        encoding="utf-8"
    )
    assert f"Ya postulaste a una igual: #{applied.id} (Nimbus Cloud)" in page


def test_notification_text(conn) -> None:
    for i, (title, family) in enumerate(
        [
            ("Help Desk", "it_support"),
            ("Soporte TI", "it_support"),
            ("Data Analyst", "data_ai"),
            ("Service Desk", "it_support"),
        ]
    ):
        db.insert_job(
            conn,
            make_job(ats_job_id=str(i), title=title, company=f"C{i}"),
            dedupe_key=str(i),
            status=Status.DISCOVERED,
            role_family=family,
        )
    title, body = daily.notification(_rows(conn), [])

    assert title == "JobBot: 4 vacantes nuevas (3 de Soporte TI, 1 de Datos / IA)"
    assert body.count("\n") == 3 and body.endswith("y 1 más")


def test_notification_quiet_without_news_but_warns_on_issues() -> None:
    assert daily.notification([], [("workday:intel", SourceReport())]) is None
    title, body = daily.notification([], [("email:indeed", SourceReport(error="HTTPError: 500"))])
    assert title == "JobBot: hoy no hay vacantes nuevas"
    assert body.startswith("Atención: email:indeed")
