"""elempleo (direct listing), Jibe and the Indeed/elempleo email parsers."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from conftest import FIXTURES
from jobbot.config import ElempleoTarget, JibeTarget
from jobbot.discovery.elempleo import ElempleoSource, parse_results
from jobbot.discovery.email_alerts import parse_elempleo, parse_indeed
from jobbot.discovery.jibe import JibeSource
from jobbot.mail.gmail import MailMessage


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --- elempleo (direct) --------------------------------------------------------------------------


def test_elempleo_result_blocks(rules) -> None:
    support, other = parse_results(_fixture("elempleo_results.html"))

    assert (support.ats_job_id, support.title, support.company, support.location) == (
        "879909",
        "Auxiliar soporte ti",
        "Empresa confidencial",
        "San José, Costa Rica",
    )
    assert support.url == "https://www.elempleo.com/cr/ofertas-trabajo/auxiliar-soporte-ti/879909"
    assert support.posted_at == datetime(2026, 10, 23)
    assert rules.evaluate(support).role_family == "it_support"
    assert other.title == "Analista de calidad administrativo & OP"  # HTML entities decoded
    assert other.posted_at == datetime(2026, 9, 2)
    assert not rules.evaluate(other).ok


def test_elempleo_source_dedupes_across_searches(make_client) -> None:
    urls: list[str] = []
    page = _fixture("elempleo_results.html")

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, text=page)

    target = ElempleoTarget(searches=["trabajo-soporte-tecnico", "trabajo-help-desk"])
    source = ElempleoSource(make_client(handler), target)
    jobs = list(source.fetch())

    assert urls == [
        "https://www.elempleo.com/cr/ofertas-empleo/trabajo-soporte-tecnico",
        "https://www.elempleo.com/cr/ofertas-empleo/trabajo-help-desk",
    ]
    assert [j.ats_job_id for j in jobs] == ["879909", "879928"]
    assert source.min_hours_between_runs == 12


# --- Jibe ---------------------------------------------------------------------------------------


def test_jibe_source_keeps_only_target_country(load_fixture, make_client, rules) -> None:
    payload = load_fixture("jibe_jobs.json")
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, json=payload)

    target = JibeTarget(
        company="Initech Services", host="careers.initech.example", country="Costa Rica"
    )
    (job,) = JibeSource(make_client(handler), target).fetch()

    assert urls == ["https://careers.initech.example/api/jobs?page=1&limit=100"]  # totalCount=2
    assert (job.source, job.ats_job_id, job.title) == (
        "jibe:initechservices",
        "careers.initech.example:50001",
        "Technical Support Engineer",
    )
    assert job.url == "https://careers.initech.example/jobs/50001"
    assert job.location == "Paraíso, Cartago, Costa Rica"
    assert job.posted_at == datetime(2026, 10, 20, 10, 0, tzinfo=UTC)
    assert "English B2" in job.description
    assert rules.evaluate(job).ok


# --- Email parsers: Indeed and elempleo ---------------------------------------------------------


def _message(html: str = "", text: str = "") -> MailMessage:
    return MailMessage(id="m", subject="alert", sender="x", text=text, html=html)


def test_indeed_email_uses_job_key_links_only() -> None:
    html = """
    <a href="https://cr.indeed.com/rc/clk/dl?jk=0123456789abcdef&amp;from=ja&amp;qd=x">
      Técnico de Soporte TI</a>
    <a href="https://cr.indeed.com/rc/clk/dl?jk=0123456789abcdef&amp;from=ja">Postúlate ahora</a>
    <a href="https://engage.indeed.com/f/a/TRACKtoken000000000000~~/SHRDseg~/p-TRACK0000">
      Help Desk Analyst</a>
    <a href="https://click.example.com/r?u=https%3A%2F%2Fcr.indeed.com%2Fviewjob%3Fjk%3DFEDCBA9876543210">
      Service Desk Agent</a>
    <a href="https://cr.indeed.com/jobs?q=soporte">Ver más empleos</a>
    """
    jobs = parse_indeed(_message(html=html), "email:indeed", "Costa Rica")

    assert [(j.ats_job_id, j.title, j.url) for j in jobs] == [
        (
            "0123456789abcdef",
            "Técnico de Soporte TI",
            "https://cr.indeed.com/viewjob?jk=0123456789abcdef",
        ),
        (
            "fedcba9876543210",
            "Service Desk Agent",
            "https://cr.indeed.com/viewjob?jk=fedcba9876543210",
        ),
    ]
    assert all(j.location == "Costa Rica" for j in jobs)


def test_elempleo_email_shares_ids_with_direct_source() -> None:
    html = (
        '<a href="https://www.elempleo.com/cr/ofertas-trabajo/auxiliar-soporte-ti/879909'
        '?utm_source=alerta">Ver vacante</a>'
    )
    (job,) = parse_elempleo(_message(html=html), "email:elempleo", "Costa Rica")

    # Same (ats, id) as the direct listing: the pipeline treats it as already seen.
    assert (job.ats, job.ats_job_id) == ("elempleo", "879909")
    assert job.title == "Auxiliar Soporte Ti"  # "Ver vacante" is not a title: slug fallback
    assert job.url == "https://www.elempleo.com/cr/ofertas-trabajo/auxiliar-soporte-ti/879909"
