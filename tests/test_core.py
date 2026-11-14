from __future__ import annotations

import httpx
import pytest

from conftest import make_job
from jobbot.core import db
from jobbot.core.http import HttpClient, NotJsonError
from jobbot.core.state import InvalidTransition, Status, check_transition
from jobbot.matching.dedupe import applied_twins, dedupe_key
from jobbot.matching.normalize import normalize_company, normalize_text, normalize_title


def test_normalize_text_strips_accents_html_and_case() -> None:
    assert normalize_text("<b>Técnico</b> de Soporte &amp; Redes") == "tecnico de soporte redes"


def test_normalize_company_drops_legal_suffixes() -> None:
    assert normalize_company("Acme & Sons Co.") == normalize_company("acme & sons")
    assert normalize_company("Acme S.A.") == "acme"


def test_normalize_title_drops_requisition_ids() -> None:
    assert normalize_title("IT Support Analyst - JR0123456") == "it support analyst"


def test_dedupe_key_matches_same_opening_across_sources() -> None:
    workday = make_job(ats="workday", company="Acme Inc.", title="Service Desk Analyst - R12345")
    linkedin = make_job(ats="linkedin", company="ACME", title="Service Desk Analyst")
    other_city = make_job(company="Acme", title="Service Desk Analyst", location="Cartago, CR")
    assert dedupe_key(workday) == dedupe_key(linkedin)
    assert dedupe_key(workday) != dedupe_key(other_city)


def test_state_machine_blocks_invalid_transitions() -> None:
    check_transition(Status.DISCOVERED, Status.SCORED)
    with pytest.raises(InvalidTransition):
        check_transition(Status.UNCERTAIN, Status.QUEUED)  # never retried automatically
    with pytest.raises(InvalidTransition):
        check_transition(Status.REJECTED, Status.QUEUED)
    check_transition(Status.SKIPPED, Status.DISCOVERED)  # rescreen after filter changes


def test_insert_touch_and_dedupe_lookup(conn) -> None:
    job = make_job()
    key = dedupe_key(job)
    assert not db.touch_seen(conn, job.ats, job.ats_job_id)

    job_id = db.insert_job(conn, job, dedupe_key=key, status=Status.DISCOVERED)
    assert db.touch_seen(conn, job.ats, job.ats_job_id)
    assert db.find_by_dedupe_key(conn, key) == job_id


def test_skipped_jobs_are_not_dedupe_originals(conn) -> None:
    job = make_job()
    key = dedupe_key(job)
    db.insert_job(conn, job, dedupe_key=key, status=Status.SKIPPED, status_reason="x")
    assert db.find_by_dedupe_key(conn, key) is None


def _row(job_id: int, company: str, title: str, location: str = "Costa Rica") -> db.JobRow:
    return db.JobRow(
        id=job_id,
        source="test",
        company=company,
        title=title,
        location=location,
        url=f"https://example.com/{job_id}",
        status=Status.DISCOVERED,
        status_reason="",
        role_family="it_support",
        first_seen_at="2026-11-01T00:00:00+00:00",
    )


def test_applied_twins_ignore_location_and_source() -> None:
    applied = [
        _row(101, "Globex Costa Rica", "Técnicos(as) de Campo", "Heredia 40101, Costa Rica"),
        _row(102, "Nimbus Cloud", "Cloud Support Engineer", "Remote - Anywhere"),
        _row(103, "Initech", "Application Support Specialist"),
        _row(104, "(Indeed)", "Help Desk Escalation Coordinator"),
    ]
    pending = [
        _row(201, "GLOBEX COSTA RICA", "Técnicos(as) de Campo", "San Pablo, Costa Rica"),
        _row(202, "Nimbus Cloud", "Cloud Support Engineer", "Remote - Worldwide"),
        _row(203, "(Indeed)", "Application Support Specialist"),  # no company in the alert
        _row(204, "Acme", "Help Desk Escalation Coordinator"),  # applied one had no company
        _row(205, "Nimbus Cloud", "Associate Platform Support Engineer"),  # other opening
        _row(206, "Acme", "Cloud Support Engineer"),  # same title, other named company
    ]
    twins = applied_twins(pending, applied)
    assert {job_id: twin.id for job_id, twin in twins.items()} == {
        201: 101,
        202: 102,
        203: 103,
        204: 104,
    }


def test_applied_twins_need_a_specific_title_without_company() -> None:
    applied = [_row(1, "Acme", "Soporte técnico")]
    assert applied_twins([_row(2, "(Indeed)", "Soporte técnico")], applied) == {}


def test_set_status_validates_transition(conn) -> None:
    job_id = db.insert_job(conn, make_job(), dedupe_key="k", status=Status.DISCOVERED)
    db.set_status(conn, job_id, Status.SCORED)
    with pytest.raises(InvalidTransition):
        db.set_status(conn, job_id, Status.CONFIRMED)
    assert db.list_jobs(conn, status=Status.SCORED)[0].id == job_id


def test_http_client_retries_failed_connections() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ConnectError("[Errno 11001] getaddrinfo failed", request=request)
        return httpx.Response(200, json={"ok": True})

    sleeps: list[float] = []
    client = HttpClient(transport=httpx.MockTransport(handler), sleep=sleeps.append)
    assert client.post_json("https://example.com/jobs", {}) == {"ok": True}
    assert calls == 3
    assert sleeps == [2.0, 8.0]


def _google_403(reason: str) -> httpx.Response:
    error = {
        "code": 403,
        "message": reason,
        "errors": [{"domain": "usageLimits", "reason": reason}],
    }
    return httpx.Response(403, json={"error": error})


def test_http_client_retries_google_rate_limits_sent_as_403() -> None:
    responses = [_google_403("userRateLimitExceeded"), httpx.Response(200, json={"id": "1"})]
    client = HttpClient(
        transport=httpx.MockTransport(lambda request: responses.pop(0)), sleep=lambda _: None
    )
    assert client.get_json("https://gmail.googleapis.com/gmail/v1/users/me/messages/1") == {
        "id": "1"
    }
    assert responses == []


@pytest.mark.parametrize(
    "response",
    [
        _google_403("insufficientPermissions"),
        httpx.Response(403, text="<html>Access denied</html>"),  # a site blocking the bot
    ],
)
def test_http_client_does_not_retry_other_403s(response: httpx.Response) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return response

    client = HttpClient(transport=httpx.MockTransport(handler), sleep=lambda _: None)
    with pytest.raises(httpx.HTTPStatusError):
        client.get_json("https://example.com/jobs")
    assert calls == 1


def test_http_client_gives_up_on_connection_errors_after_max_retries() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("[Errno 11001] getaddrinfo failed", request=request)

    client = HttpClient(transport=httpx.MockTransport(handler), max_retries=2, sleep=lambda _: None)
    with pytest.raises(httpx.ConnectError):
        client.get_json("https://example.com/jobs")
    assert calls == 3


def test_http_client_explains_a_page_sent_instead_of_json() -> None:
    # A site under maintenance answers 200 with an HTML page (Workday, 2026-11-14).
    page = "<html><head><title>\n  Workday is currently unavailable\n</title></head></html>"
    client = HttpClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=page, headers={"Content-Type": "text/html"})
        )
    )
    with pytest.raises(NotJsonError) as caught:
        client.post_json("https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Ext/jobs", {})
    message = str(caught.value)
    assert "HTTP 200" in message
    assert "text/html" in message
    assert "«Workday is currently unavailable»" in message
    assert "mantenimiento" in message
    assert isinstance(caught.value, ValueError)  # callers that catch ValueError keep working


def test_http_client_names_an_empty_answer_and_a_redirect_to_another_site() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "acme.wd5.myworkdayjobs.com":
            return httpx.Response(302, headers={"Location": "https://status.example.com/down"})
        return httpx.Response(200, text="")

    client = HttpClient(transport=httpx.MockTransport(handler))
    with pytest.raises(NotJsonError) as caught:
        client.get_json("https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Ext/jobs")
    assert "respuesta vacía" in str(caught.value)
    assert "redirigió a status.example.com" in str(caught.value)
