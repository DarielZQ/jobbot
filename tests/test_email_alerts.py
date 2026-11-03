"""Email alert ingestion (LinkedIn, CompuTrabajo) and the read-only Gmail client, without network.

The fixtures are synthetic: they follow the expected layout, not real emails. Replace them with
sanitized real samples from `jobbot alerts-sample` once alerts arrive.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest

from conftest import FIXTURES
from jobbot.discovery.base import SourceNotConfigured
from jobbot.discovery.email_alerts import (
    EmailAlertSource,
    parse_computrabajo,
    parse_indeed,
    parse_linkedin,
)
from jobbot.discovery.pipeline import run_source
from jobbot.mail.gmail import GmailClient, MailMessage, access_token


def _message(text: str = "", html: str = "") -> MailMessage:
    return MailMessage(id="m1", subject="alert", sender="x", text=text, html=html)


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --- LinkedIn -----------------------------------------------------------------------------------


def test_linkedin_text_alert_blocks(rules) -> None:
    jobs = parse_linkedin(_message(text=_fixture("email_linkedin_alert.txt")), "email:linkedin", "")

    assert [(j.ats_job_id, j.title, j.company, j.location) for j in jobs] == [
        ("4012345678", "Service Desk Analyst", "Acme Corp", "Heredia, Heredia, Costa Rica"),
        ("4012345679", "Senior Help Desk Engineer", "Beta Inc", "San José, San José, Costa Rica"),
        ("4012345680", "IT Support Technician", "Gamma", "Costa Rica (Remote)"),
    ]
    assert jobs[0].url == "https://www.linkedin.com/jobs/view/4012345678/"  # no tracking params
    assert jobs[2].remote
    assert [rules.evaluate(j).ok for j in jobs] == [True, False, True]  # "Senior" is excluded


def test_linkedin_html_fallback_uses_default_location() -> None:
    message = _message(html=_fixture("email_linkedin_alert.html"))
    jobs = parse_linkedin(message, "email:linkedin", "Costa Rica")

    assert [(j.ats_job_id, j.title, j.location) for j in jobs] == [
        ("4012345678", "Service Desk Analyst", "Costa Rica"),
        ("4012345681", "Technical Support & Help Desk Analyst", "Costa Rica"),
    ]


# --- Indeed -------------------------------------------------------------------------------------
# The fixtures follow the layout of real alerts (2026-10-29), with made-up jobs and tokens.


def test_indeed_digest_text_blocks(rules) -> None:
    message = _message(text=_fixture("email_indeed_alert.txt"))
    jobs = parse_indeed(message, "email:indeed", "Costa Rica")

    assert [(j.title, j.company, j.location) for j in jobs] == [
        ("Service Desk Agent", "Acme Corp", "Heredia, Provincia de Heredia, Costa Rica"),
        ("Production Supervisor", "Beta Inc", "Alajuela, Provincia de Alajuela, Costa Rica"),
        ("IT Support Technician", "Gamma", "Remote, Costa Rica"),
        (
            "Facilities Technician II - Cartago | Day Shift",
            "Delta Medical",
            "Cartago, Provincia de Cartago, Costa Rica",
        ),
    ]
    assert jobs[0].url == "https://engage.indeed.com/f/a/JOB1token000~~/SHRDseg~/job1TOKEN000~~"
    assert jobs[2].remote
    assert [rules.evaluate(j).ok for j in jobs] == [True, False, True, False]


def test_indeed_ids_survive_new_tracking_tokens() -> None:
    text = _fixture("email_indeed_alert.txt")
    retracked = text.replace("token", "other")
    first = parse_indeed(_message(text=text), "email:indeed", "Costa Rica")
    again = parse_indeed(_message(text=retracked), "email:indeed", "Costa Rica")
    assert [j.ats_job_id for j in first] == [j.ats_job_id for j in again]
    assert len({j.ats_job_id for j in first}) == 4


def test_indeed_single_job_email() -> None:
    message = _message(text=_fixture("email_indeed_match.txt"))
    (job,) = parse_indeed(message, "email:indeed", "Costa Rica")

    assert (job.title, job.company, job.location) == (
        "Agente IT Helpdesk",
        "Epsilon Talent",
        "San José, Provincia de San José, Costa Rica",
    )
    assert job.url == "https://cts.indeed.com/v3/VIEWtoken0000"


def test_indeed_job_key_links_win_over_text() -> None:
    html = '<a href="https://cr.indeed.com/rc/clk?jk=0123456789abcdef&amp;from=ja">Help Desk</a>'
    message = _message(text=_fixture("email_indeed_alert.txt"), html=html)
    (job,) = parse_indeed(message, "email:indeed", "Costa Rica")
    assert job.url == "https://cr.indeed.com/viewjob?jk=0123456789abcdef"


# --- CompuTrabajo -------------------------------------------------------------------------------


def test_computrabajo_alert_links(rules) -> None:
    message = _message(html=_fixture("email_computrabajo_alert.html"))
    jobs = {j.ats_job_id: j for j in parse_computrabajo(message, "email:computrabajo", "")}

    soporte = jobs["0A1B2C3D4E5F60718293A4B5C6D7E8F9"]
    # The tracking redirect is decoded; the anchor text wins over the URL slug.
    assert soporte.title == "Técnico de Soporte TI"
    assert soporte.location == "Heredia, Costa Rica"
    assert soporte.url == (
        "https://cr.computrabajo.com/ofertas-de-trabajo/"
        "oferta-de-trabajo-de-tecnico-de-soporte-ti-en-heredia-0A1B2C3D4E5F60718293A4B5C6D7E8F9"
    )
    mesa = jobs["FFEEDDCCBBAA99887766554433221100"]
    # "Ver oferta" is not a title: it falls back to the slug.
    assert (mesa.title, mesa.location) == (
        "Agente De Mesa De Ayuda Bilingue",
        "Moravia, Costa Rica",
    )
    assert rules.evaluate(soporte).ok and rules.evaluate(mesa).ok

    cajero = jobs["11111111111111111111111111111111"]
    assert not rules.evaluate(cajero).ok  # not a target role (and Liberia is outside the GAM)


def test_computrabajo_digest_cards_real_structure(rules) -> None:
    message = _message(html=_fixture("email_computrabajo_digest.html"))
    jobs = {j.ats_job_id: j for j in parse_computrabajo(message, "email:computrabajo", "")}

    # Promotional links (o_grid, unsubscribe, app) are not offers.
    assert len(jobs) == 3
    operario = jobs["1A2B3C4D5E6F70015EED5EED5EED5EED"]
    # Badges, the company rating and the salary are cut away; "(a)" survives.
    assert (operario.title, operario.company, operario.location) == (
        "Operario(a) Producción I",
        "Laboratorio Ejemplo",
        "Alajuela, Costa Rica",
    )
    soporte = jobs["1A2B3C4D5E6F70025EED5EED5EED5EED"]
    assert (soporte.title, soporte.company) == (
        "Analista de Soporte Técnico Nivel 1",
        "Servicios Ejemplo S.A.",
    )
    assert rules.evaluate(soporte).role_family == "it_support"
    pastelero = jobs["1A2B3C4D5E6F70035EED5EED5EED5EED"]
    # No rating: the company is whatever sits between the title and the location.
    assert (pastelero.title, pastelero.company) == (
        "Técnico Pastelero y de Panificación",
        "Importante empresa del sector",
    )
    assert not rules.evaluate(operario).ok and not rules.evaluate(pastelero).ok


def test_computrabajo_inclusive_forms_match_glued_slug() -> None:
    href = (
        "https://cr.computrabajo.com/ofertas-de-trabajo/"
        "oferta-de-trabajo-de-coordinadora-administrativoa-en-san-jose-"
        "1A2B3C4D5E6F70045EED5EED5EED5EED"
    )
    html = (
        f'<a href="{href}">Coordinador(a) Administrativo/a 4.1 Empresa Uno San José, San José</a>'
    )
    (job,) = parse_computrabajo(_message(html=html), "email:computrabajo", "")
    assert (job.title, job.company) == ("Coordinador(a) Administrativo/a", "Empresa Uno")


def test_email_alert_source_prefers_version_with_company(conn, rules) -> None:
    slug = "oferta-de-trabajo-de-analista-de-soporte-en-heredia-1A2B3C4D5E6F70025EED5EED5EED5EED"
    url = f"https://cr.computrabajo.com/ofertas-de-trabajo/{slug}"
    button_only = _message(html=f'<a href="{url}">Postúlate</a>')
    card = _message(
        html=f'<a href="{url}">Analista de Soporte 4.2 Empresa Dos Heredia, Heredia</a>'
    )
    mail = FakeMail({"a": button_only, "b": card})
    source = EmailAlertSource(
        "computrabajo", mail, "from:computrabajo.com", lookback_days=14, max_messages=50
    )

    (job,) = source.fetch()

    assert (job.title, job.company) == ("Analista de Soporte", "Empresa Dos")


# --- Source and pipeline ------------------------------------------------------------------------


class FakeMail:
    def __init__(self, messages: dict[str, MailMessage]) -> None:
        self.messages = messages
        self.queries: list[str] = []

    def search(self, query: str, max_messages: int) -> list[str]:
        self.queries.append(query)
        return list(self.messages)[:max_messages]

    def get(self, message_id: str) -> MailMessage:
        return self.messages[message_id]


def test_email_alert_source_dedupes_across_messages(conn, rules) -> None:
    text = _fixture("email_linkedin_alert.txt")
    mail = FakeMail({"a": _message(text=text), "b": _message(text=text)})
    source = EmailAlertSource("linkedin", mail, "from:linkedin", lookback_days=14, max_messages=50)

    report = run_source(source, conn, rules)

    assert mail.queries == ["(from:linkedin) newer_than:14d"]
    assert (report.new_matched, report.new_skipped, report.seen) == (2, 1, 0)


def test_unconfigured_gmail_is_reported_not_raised(conn, rules, tmp_path: Path) -> None:
    def token() -> str:
        return access_token(tmp_path / "missing.json", tmp_path / "token.json")

    mail = GmailClient(httpx_client_unused(), token)
    source = EmailAlertSource("linkedin", mail, "from:x", lookback_days=1, max_messages=1)

    report = run_source(source, conn, rules)

    assert "missing.json" in report.not_configured
    assert report.error == ""


def httpx_client_unused():
    from jobbot.core.http import HttpClient

    def fail(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected before configuration")

    return HttpClient(transport=httpx.MockTransport(fail), sleep=lambda _: None)


def test_access_token_requires_login(tmp_path: Path) -> None:
    credentials = tmp_path / "gmail_credentials.json"
    credentials.write_text("{}", encoding="utf-8")
    with pytest.raises(SourceNotConfigured, match="gmail-login"):
        access_token(credentials, tmp_path / "gmail_token.json")


# --- Gmail client -------------------------------------------------------------------------------


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def test_gmail_client_search_pagination_and_decoding(make_client) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        url = str(request.url)
        if "/messages?" in url:
            if "pageToken=p2" in url:
                return httpx.Response(200, json={"messages": [{"id": "m2"}]})
            return httpx.Response(200, json={"messages": [{"id": "m1"}], "nextPageToken": "p2"})
        payload = {
            "payload": {
                "mimeType": "multipart/alternative",
                "headers": [
                    {"name": "Subject", "value": "Alerta"},
                    {"name": "From", "value": "LI"},
                ],
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": _b64("Técnico de soporte")}},
                    {"mimeType": "text/html", "body": {"data": _b64("<b>hola</b>")}},
                ],
            }
        }
        return httpx.Response(200, content=json.dumps(payload))

    mail = GmailClient(make_client(handler), token=lambda: "tok")

    assert mail.search("from:x newer_than:14d", max_messages=10) == ["m1", "m2"]
    message = mail.get("m1")
    assert (message.subject, message.text, message.html) == (
        "Alerta",
        "Técnico de soporte",
        "<b>hola</b>",
    )
    assert all(r.headers["Authorization"] == "Bearer tok" for r in seen)
    assert "q=from%3Ax%20newer_than%3A14d" in str(seen[0].url)
