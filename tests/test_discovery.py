from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime

import httpx
import pytest

from conftest import FIXTURES, make_job
from jobbot.config import (
    AshbyTarget,
    DeelTarget,
    GreenhouseTarget,
    ICimsTarget,
    LeverTarget,
    SuccessFactorsTarget,
    WorkdayTarget,
    load_search_rules,
)
from jobbot.core import db
from jobbot.core.models import Job
from jobbot.core.state import Status
from jobbot.discovery.ashby import AshbySource
from jobbot.discovery.base import Source
from jobbot.discovery.deel import DeelSource
from jobbot.discovery.greenhouse import GreenhouseSource
from jobbot.discovery.icims import ICimsSource
from jobbot.discovery.lever import LeverSource
from jobbot.discovery.pipeline import run_source
from jobbot.discovery.successfactors import SuccessFactorsSource, job_description
from jobbot.discovery.workday import WorkdaySource, find_country_facet
from jobbot.matching.rules import RuleSet

WORKDAY = WorkdayTarget(
    company="Acme",
    host="acme.wd1.myworkdayjobs.com",
    tenant="acme",
    site="Ext",
    country="Costa Rica",
)


def test_find_country_facet_prefers_country_parameter(load_fixture) -> None:
    facets = load_fixture("workday_page.json")["facets"]
    assert find_country_facet(facets, "Costa Rica") == ("locationCountry", ["cr-country-id"])
    assert find_country_facet(facets, "Panama") is None


def test_workday_source_applies_country_facet_and_builds_jobs(load_fixture, make_client) -> None:
    page = load_fixture("workday_page.json")
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            requests.append(json.loads(request.content))
            return httpx.Response(200, json=page)
        return httpx.Response(200, json={"jobPostingInfo": {"jobDescription": "<p>Hi</p>"}})

    source = WorkdaySource(make_client(handler), WORKDAY)
    jobs = list(source.fetch())

    assert requests[0]["appliedFacets"] == {}
    assert requests[1]["appliedFacets"] == {"locationCountry": ["cr-country-id"]}
    assert len(requests) == 2  # total=3 fits in one page
    assert [j.ats_job_id for j in jobs] == ["acme:R0001", "acme:R0002", "acme:R0003"]
    assert jobs[0].url == (
        "https://acme.wd1.myworkdayjobs.com/Ext/job/Costa-Rica-Heredia/Service-Desk-Analyst-I_R0001"
    )
    # "2 Locations" gets the country appended because the facet guarantees it.
    assert jobs[2].location == "2 Locations | Costa Rica"
    assert source.enrich(jobs[0]).description == "<p>Hi</p>"
    # "Posted Today" / "Posted 3 Days Ago": a date, marked as approximate
    assert all(j.posted_at is not None and j.posted_approx for j in jobs)


def test_greenhouse_source(load_fixture, make_client) -> None:
    payload = load_fixture("greenhouse_jobs.json")
    client = make_client(lambda request: httpx.Response(200, json=payload))
    jobs = list(GreenhouseSource(client, GreenhouseTarget(company="Acme", token="acme")).fetch())

    assert [j.ats_job_id for j in jobs] == ["acme:4012345", "acme:4012346"]
    assert jobs[0].remote and jobs[0].location == "Remote - LATAM"
    assert jobs[0].posted_at is not None


def test_greenhouse_reads_a_bare_remote_as_the_company_scope(load_fixture, make_client) -> None:
    payload = load_fixture("greenhouse_jobs.json")
    payload["jobs"][0]["location"]["name"] = "Remote"
    client = make_client(lambda request: httpx.Response(200, json=payload))
    target = GreenhouseTarget(company="Acme", token="acme", remote_scope="Worldwide")

    first, second = GreenhouseSource(client, target).fetch()

    assert first.location == "Remote - Worldwide"
    assert second.location == "Remote - US only"  # a location with a place is kept


def test_ashby_source(load_fixture, make_client, rules) -> None:
    payload = load_fixture("ashby_board.json")
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, json=payload)

    target = AshbyTarget(company="Acme", board="acme", remote_scope="Worldwide")
    jobs = list(AshbySource(make_client(handler), target).fetch())

    assert urls == ["https://api.ashbyhq.com/posting-api/job-board/acme"]
    # The unlisted posting is left out
    assert [j.ats_job_id for j in jobs] == ["acme:a1b2c3d4-0001", "acme:a1b2c3d4-0002"]
    support, engineer = jobs
    assert support.title == "Customer Support Specialist"
    assert support.location == "Remote - Worldwide" and support.remote
    assert support.posted_at == datetime(2026, 11, 1, 12, tzinfo=UTC)
    assert engineer.location == "Mexico, Costa Rica" and engineer.remote  # workplaceType
    assert engineer.url == "https://jobs.ashbyhq.com/acme/a1b2c3d4-0002"
    assert all(rules.evaluate(j).ok for j in jobs)


def test_deel_reads_the_jobs_inside_its_careers_page(make_client, rules) -> None:
    page = (FIXTURES / "deel_careers.html").read_text(encoding="utf-8")
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, text=page)

    jobs = list(DeelSource(make_client(handler), DeelTarget()).fetch())

    assert urls == ["https://www.deel.com/careers/"]
    # The second job spans two payload chunks; the unlisted one is left out
    assert [j.title for j in jobs] == [
        "Customer Support Specialist | LATAM",
        "Account Executive | Brazil",
    ]
    latam, brazil = jobs
    assert latam.location == "Mexico, Costa Rica" and latam.remote
    assert latam.url == "https://www.deel.com/careers/position/?ashby_jid=00000000-0001"
    assert latam.posted_at == datetime(2026, 11, 5, 10, tzinfo=UTC)
    # Only the one open to Costa Rica passes the preset's location filters
    assert rules.evaluate(latam).ok and not rules.evaluate(brazil).ok


def test_deel_page_without_jobs_is_an_error(conn, rules, make_client) -> None:
    client = make_client(lambda request: httpx.Response(200, text="<html>Careers</html>"))

    report = run_source(DeelSource(client, DeelTarget()), conn, rules)

    assert "ya no trae las vacantes" in report.error


def _icims_client(make_client, requested: list[str]):
    pages = {
        name: (FIXTURES / f"{name}.html").read_text(encoding="utf-8")
        for name in ("icims_search_p0", "icims_search_p1", "icims_job")
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if "/jobs/search" in request.url.path:
            # Past the last page the portal shows the last page again
            page = "icims_search_p0" if request.url.params["pr"] == "0" else "icims_search_p1"
            return httpx.Response(200, text=pages[page])
        return httpx.Response(200, text=pages["icims_job"])

    return make_client(handler)


ICIMS = ICimsTarget(company="Acme", host="jobs-acme.icims.com", search="searchLocation=1-2-Place")


def test_icims_reads_search_pages_until_nothing_is_new(make_client) -> None:
    requested: list[str] = []
    source = ICimsSource(_icims_client(make_client, requested), ICIMS)

    jobs = list(source.fetch())

    assert source.name == "icims:acme"
    assert [(j.ats_job_id, j.title) for j in jobs] == [
        ("acme:1201", "Service Desk Analyst L1"),
        ("acme:1202", "Payroll Specialist"),
        ("acme:1150", "Senior Accountant"),
    ]
    assert jobs[1].location == "CR-H-Costa Rica | CO-Bogotá"
    assert jobs[0].url == "https://jobs-acme.icims.com/jobs/1201/service-desk-analyst-l1/job"
    assert requested == [
        "https://jobs-acme.icims.com/jobs/search?ss=1&searchLocation=1-2-Place&in_iframe=1&pr=0",
        "https://jobs-acme.icims.com/jobs/search?ss=1&searchLocation=1-2-Place&in_iframe=1&pr=1",
        "https://jobs-acme.icims.com/jobs/search?ss=1&searchLocation=1-2-Place&in_iframe=1&pr=2",
    ]

    detailed = source.enrich(jobs[0])
    assert detailed.posted_at == datetime(2026, 11, 11, 5, tzinfo=UTC)
    assert "escalate to tier 2" in detailed.description
    assert requested[-1] == f"{jobs[0].url}?in_iframe=1"


def test_any_role_companies_pass_without_a_family(make_client) -> None:
    jobs = list(ICimsSource(_icims_client(make_client, []), ICIMS).fetch())
    search = load_search_rules()
    usual = RuleSet(search)
    search.any_role_companies = ["ACME"]  # compared without case or accents
    any_role = RuleSet(search)

    assert [usual.evaluate(j).reason for j in jobs] == [
        "",
        "title_not_target_role",
        "title_not_target_role",
    ]
    assert [(r.ok, r.reason, r.role_family) for r in map(any_role.evaluate, jobs)] == [
        (True, "", "it_support"),
        (True, "", ""),  # any role at that company
        (False, "title_excluded: senior", ""),  # seniority still applies
    ]


def test_lever_source(load_fixture, make_client) -> None:
    payload = load_fixture("lever_postings.json")
    client = make_client(lambda request: httpx.Response(200, json=payload))
    (job,) = LeverSource(client, LeverTarget(company="Acme", slug="acme")).fetch()

    assert job.title == "Cloud Support Associate"
    assert job.location == "San José, Costa Rica"
    assert "3+ years" in job.description


SF_TARGET = SuccessFactorsTarget(
    company="Acme", base_url="https://jobs.acme.com/", keywords="costa rica"
)


def test_successfactors_reads_the_search_page_not_the_services_path(make_client) -> None:
    pages = {
        None: (FIXTURES / "successfactors_search.html").read_text(encoding="utf-8"),
        "2": (FIXTURES / "successfactors_search_page2.html").read_text(encoding="utf-8"),
    }
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(200, text=pages[request.url.params.get("startrow")])

    source = SuccessFactorsSource(make_client(handler), SF_TARGET)
    first, second, third = source.fetch()

    # robots.txt of these sites disallows /services/ (the RSS feed); /search/ is allowed (ADR-028).
    assert seen_urls == [
        "https://jobs.acme.com/search/?q=&locationsearch=costa%20rica&locale=en_US",
        "https://jobs.acme.com/search/?q=&locationsearch=costa%20rica&locale=en_US&startrow=2",
    ]
    assert first.title == "Junior Networking Agent & Support (Entry Level)"
    assert first.location == "Heredia, Costa Rica, CR"
    assert first.url == (
        "https://jobs.acme.com/job/Heredia-Junior-Networking-Agent-%28Entry-Level%29/1413280300/"
    )
    assert first.ats_job_id == "jobs.acme.com:1413280300"
    assert first.posted_at == datetime(2026, 10, 22, tzinfo=UTC)
    assert (second.posted_at, second.remote) == (None, True)
    assert third.title == "IT Support Analyst"
    assert source.listing_complete


def test_successfactors_detail_page_gives_description_and_date(make_client) -> None:
    detail = (FIXTURES / "successfactors_job.html").read_text(encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/job/Heredia-Junior-Networking-Agent/1413280300/"
        return httpx.Response(200, text=detail)

    job = make_job(url="https://jobs.acme.com/job/Heredia-Junior-Networking-Agent/1413280300/")
    enriched = SuccessFactorsSource(make_client(handler), SF_TARGET).enrich(job)

    # The description nests spans of its own; it ends at the span that opened it.
    assert enriched.description == (
        '<div><p>Entry level role, <span style="font-weight:bold">no experience</span>'
        " required.</p></div>"
    )
    assert enriched.posted_at == datetime(2026, 10, 22, tzinfo=UTC)


def test_successfactors_description_span_may_carry_more_attributes() -> None:
    page = '<div class="job"><span itemprop="description" class="jobdescription"><p>Hi</p></span>'
    assert job_description(page) == "<p>Hi</p>"


def test_successfactors_without_results_is_a_complete_empty_listing(make_client) -> None:
    page = '<div id="noresults"><label>There are currently no open positions.</label></div>'
    source = SuccessFactorsSource(make_client(lambda r: httpx.Response(200, text=page)), SF_TARGET)

    assert list(source.fetch()) == []
    assert source.listing_complete


def test_successfactors_page_that_loads_jobs_with_javascript_is_explained(make_client) -> None:
    page = '<div id="jobSearch_j_id1"></div><script src="/platform/js/search/search.js"></script>'
    source = SuccessFactorsSource(make_client(lambda r: httpx.Response(200, text=page)), SF_TARGET)

    with pytest.raises(ValueError, match="carga con JavaScript"):
        list(source.fetch())


class FakeSource(Source):
    def __init__(self, name: str, jobs: Iterable[Job]) -> None:
        self.name = name
        self.jobs = list(jobs)
        self.enriched: list[str] = []

    def fetch(self) -> Iterable[Job]:
        return self.jobs

    def enrich(self, job: Job) -> Job:
        self.enriched.append(job.ats_job_id)
        return job.model_copy(update={"description": "Entry level role."})


def test_pipeline_filters_dedupes_and_is_idempotent(conn, rules) -> None:
    good = make_job(ats="workday", ats_job_id="1", title="Service Desk Analyst")
    senior = make_job(ats="workday", ats_job_id="2", title="Senior Service Desk Analyst")
    workday = FakeSource("workday:acme", [good, senior])

    report = run_source(workday, conn, rules)
    assert (report.new_matched, report.new_skipped, report.seen) == (1, 1, 0)
    assert workday.enriched == ["1"]  # details fetched only for the posting that passed

    same_opening = make_job(ats="lever", ats_job_id="x", title="Service Desk Analyst")
    report = run_source(FakeSource("lever:acme", [same_opening]), conn, rules)
    assert report.skip_reasons["duplicate_of"] == 1

    report = run_source(workday, conn, rules)
    assert (report.new_matched, report.new_skipped, report.seen) == (0, 0, 2)

    discovered = db.list_jobs(conn, status=Status.DISCOVERED)
    assert [row.title for row in discovered] == ["Service Desk Analyst"]


def test_alert_job_stored_without_company_gets_it_and_is_screened_again(conn) -> None:
    search = load_search_rules()
    search.location.local_exclude = [r"\bliberia\b"]
    rules = RuleSet(search)

    def alert(job_id: str, title: str, company: str = "(Indeed)", place: str = "Costa Rica"):
        return make_job(
            source="email:indeed", ats="indeed", ats_job_id=job_id, title=title,
            company=company, location=place,
        )  # fmt: skip

    support = "Technical Support Engineer, Storage"
    run_source(
        FakeSource("email:indeed", [alert("a", support), alert("b", "IT Support Analyst"),
                                    alert("c", "Service Desk Analyst")]),
        conn, rules,
    )  # fmt: skip
    site = make_job(source="greenhouse:acme", ats="greenhouse", ats_job_id="9", title=support,
                    company="Acme", location="San Jose, Costa Rica")  # fmt: skip
    run_source(FakeSource("greenhouse:acme", [site]), conn, rules)
    rows = {row.title: row for row in db.list_jobs(conn)}
    db.set_status(conn, rows["Service Desk Analyst"].id, Status.SUBMITTED, "applied_manually")

    # The same alerts again, now read with their company and place.
    named = [
        alert("a", support, "Acme Software", "San José, Provincia de San José, Costa Rica"),
        alert("b", "IT Support Analyst", "Beta Hotels", "Liberia, Guanacaste, Costa Rica"),
        alert("c", "Service Desk Analyst", "Gamma", "Heredia, Costa Rica"),
    ]
    report = run_source(FakeSource("email:indeed", named), conn, rules)

    rows = {(row.source, row.title): row for row in db.list_jobs(conn)}
    from_alert = rows[("email:indeed", support)]
    from_site = rows[("greenhouse:acme", support)]
    # The company's own listing stays; the alert copy is the duplicate.
    assert (from_alert.company, from_alert.status) == ("Acme Software", Status.SKIPPED)
    assert from_alert.status_reason == f"duplicate_of: {from_site.id}"
    assert from_site.status is Status.DISCOVERED
    far = rows[("email:indeed", "IT Support Analyst")]
    assert (far.status, far.status_reason) == (Status.SKIPPED, "location_outside_area: liberia")
    # The candidate's decision stands; only the company is filled in.
    applied = rows[("email:indeed", "Service Desk Analyst")]
    assert (applied.company, applied.status) == ("Gamma", Status.SUBMITTED)
    assert (report.seen, report.screened_out) == (3, 2)


class FullListing(FakeSource):
    """A site whose API lists every open posting (Workday, Greenhouse...)."""

    def fetch(self) -> Iterable[Job]:
        yield from self.jobs
        self.listing_complete = True


def test_jobs_missing_from_a_complete_listing_are_taken_down(conn, rules) -> None:
    kept = make_job(
        source="greenhouse:acme", ats="greenhouse", ats_job_id="1", title="Service Desk Analyst"
    )
    closed = make_job(
        source="greenhouse:acme", ats="greenhouse", ats_job_id="2", title="Help Desk Technician"
    )
    run_source(FullListing("greenhouse:acme", [kept, closed]), conn, rules)
    assert db.taken_down(conn) == set()
    with conn:  # that run was yesterday
        conn.execute("UPDATE jobs SET last_seen_at = '2000-01-01T00:00:00+00:00'")

    run_source(FullListing("greenhouse:acme", [kept]), conn, rules)
    assert {db.get_job(conn, i).title for i in db.taken_down(conn)} == {"Help Desk Technician"}

    run_source(FullListing("greenhouse:acme", [kept, closed]), conn, rules)  # back up again
    assert db.taken_down(conn) == set()


def test_partial_listings_never_mark_jobs_as_taken_down(conn, rules) -> None:
    job = make_job(source="jobicy", ats="jobicy", ats_job_id="1", title="Service Desk Analyst")
    run_source(FakeSource("jobicy", [job]), conn, rules)
    with conn:  # that run was yesterday
        conn.execute("UPDATE jobs SET last_seen_at = '2000-01-01T00:00:00+00:00'")

    # A feed of the newest postings only, or a listing cut short by an error
    run_source(FakeSource("jobicy", []), conn, rules)

    class CutShort(FullListing):
        def fetch(self) -> Iterable[Job]:
            raise httpx.ReadTimeout("slow")
            yield  # a generator, like the real sources

    assert run_source(CutShort("jobicy", []), conn, rules).error
    assert db.taken_down(conn) == set()


def test_workday_listing_is_complete_only_through_the_country_facet(
    load_fixture, make_client
) -> None:
    page = load_fixture("workday_page.json")
    source = WorkdaySource(make_client(lambda request: httpx.Response(200, json=page)), WORKDAY)
    list(source.fetch())
    assert source.listing_complete

    no_facet = {**page, "facets": []}
    source = WorkdaySource(make_client(lambda request: httpx.Response(200, json=no_facet)), WORKDAY)
    list(source.fetch())
    assert not source.listing_complete


def test_rescreen_reopens_and_skips_without_network(conn, rules) -> None:
    from jobbot.discovery.pipeline import rescreen

    wrong_skip = make_job(ats_job_id="a", title="Incident Management Engineer")
    db.insert_job(
        conn,
        wrong_skip,
        dedupe_key="ka",
        status=Status.SKIPPED,
        status_reason="title_not_target_role",
    )
    now_bad = make_job(ats_job_id="b", title="Senior Service Desk Analyst")
    db.insert_job(
        conn, now_bad, dedupe_key="kb", status=Status.DISCOVERED, role_family="it_support"
    )
    duplicate = make_job(ats_job_id="c", title="Service Desk Analyst")
    db.insert_job(
        conn, duplicate, dedupe_key="kc", status=Status.SKIPPED, status_reason="duplicate_of: 1"
    )

    changes = rescreen(conn, rules)

    assert (changes["reopened"], changes["newly_skipped"]) == (1, 1)
    discovered = db.list_jobs(conn, status=Status.DISCOVERED)
    assert [(r.title, r.role_family) for r in discovered] == [
        ("Incident Management Engineer", "it_support")
    ]
    skipped = {r.title: r.status_reason for r in db.list_jobs(conn, status=Status.SKIPPED)}
    assert skipped["Senior Service Desk Analyst"].startswith("title_excluded")
    assert skipped["Service Desk Analyst"] == "duplicate_of: 1"  # duplicates are left alone


def test_next_run_fetches_details_of_jobs_reopened_offline(conn, rules) -> None:
    def stored(ats_job_id: str, title: str, reason: str = "") -> Job:
        job = make_job(ats="workday", ats_job_id=ats_job_id, title=title)
        db.insert_job(
            conn, job, dedupe_key=ats_job_id, status=Status.DISCOVERED, status_reason=reason
        )
        return job

    junior = stored("j", "Network Technician")
    demanding = stored("d", "Windows Administrator")
    by_hand = stored("h", "IT Asset Analyst", reason=db.REOPENED_MANUALLY)

    class Detailed(FakeSource):
        def enrich(self, job: Job) -> Job:
            self.enriched.append(job.ats_job_id)
            text = "Security clearance required." if job.ats_job_id != "j" else "Entry level."
            return job.model_copy(update={"description": text})

    source = Detailed("workday:acme", [junior, demanding, by_hand])
    report = run_source(source, conn, rules)

    assert source.enriched == ["j", "d"]  # the candidate's own reopening is not second-guessed
    assert (report.seen, report.screened_out) == (3, 1)
    open_titles = {r.title for r in db.list_jobs(conn, status=Status.DISCOVERED)}
    assert open_titles == {"Network Technician", "IT Asset Analyst"}

    source.enriched.clear()
    run_source(source, conn, rules)
    assert source.enriched == []  # details are fetched only once


def test_pipeline_reports_http_errors(conn, rules) -> None:
    class Broken(Source):
        name = "broken"

        def __init__(self) -> None:
            pass

        def fetch(self) -> Iterable[Job]:
            raise httpx.ConnectError("boom")

    report = run_source(Broken(), conn, rules)
    assert report.error.startswith("Sin conexión: no se pudo llegar al sitio")
    assert report.error.endswith("[ConnectError: boom]")


def test_pipeline_error_includes_the_api_explanation(conn, rules, make_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"code": 403, "message": "Mail not enabled"}})

    client = make_client(handler)

    class Gmail(Source):
        name = "email:elempleo"

        def __init__(self) -> None:
            pass

        def fetch(self) -> Iterable[Job]:
            client.get_json("https://gmail.googleapis.com/gmail/v1/users/me/messages/1")
            return []

    report = run_source(Gmail(), conn, rules)
    assert report.error.startswith("Acceso negado: el sitio rechazó la consulta.")
    assert "Motivo que dio el sitio: Mail not enabled." in report.error
    assert report.error.endswith("[HTTP 403 · gmail.googleapis.com]")


def test_pipeline_reports_a_maintenance_page_in_plain_words(conn, rules, make_client) -> None:
    page = "<html><title>Workday is currently unavailable</title></html>"
    client = make_client(
        lambda _: httpx.Response(200, text=page, headers={"Content-Type": "text/html"})
    )

    report = run_source(WorkdaySource(client, WORKDAY), conn, rules)
    assert report.error.startswith("Sin datos: el sitio respondió una página")
    assert "JSONDecodeError" not in report.error


def test_pipeline_reports_unexpected_errors_instead_of_stopping(conn, rules) -> None:
    class Odd(Source):
        name = "odd"

        def __init__(self) -> None:
            pass

        def fetch(self) -> Iterable[Job]:
            yield make_job()
            raise KeyError("externalPath")

    report = run_source(Odd(), conn, rules)
    assert report.error.startswith("La respuesta del sitio cambió de forma")
    assert report.error.endswith("[KeyError: 'externalPath']")
    assert report.new_matched + report.new_skipped == 1  # what came before the error is kept


def test_bot_check_is_explained_and_never_retried(conn, rules, make_client) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        page = "<html><body>Security Check. Enable JavaScript and cookies to continue</body></html>"
        headers = {"Content-Type": "text/html", "Server": "cloudflare", "cf-mitigated": "challenge"}
        return httpx.Response(429, text=page, headers=headers)

    report = run_source(WorkdaySource(make_client(handler), WORKDAY), conn, rules)

    assert len(calls) == 1  # ADR-003: no retries against a bot check
    assert report.error.startswith("Bloqueo anti-bots: Cloudflare, la protección del sitio,")
    assert "No es una falla de JobBot ni un cambio en la página" in report.error
    assert report.error.endswith("[HTTP 429 · acme.wd1.myworkdayjobs.com]")


def test_bot_check_page_without_cloudflare_header_is_recognized() -> None:
    from jobbot.core.http import is_challenge

    page = "<title>Just a moment...</title>"
    html = {"Content-Type": "text/html"}
    assert is_challenge(httpx.Response(503, text=page, headers=html))
    assert not is_challenge(httpx.Response(503, text="<title>Down</title>", headers=html))
    assert not is_challenge(httpx.Response(429, json={"error": "slow down"}))


@pytest.mark.parametrize(
    ("status", "start"),
    [
        (429, "Demasiadas consultas: el sitio pidió bajar el ritmo"),
        (404, "Dirección no encontrada: la página de empleos ya no está en esa URL"),
        (502, "Falla del sitio: su servidor tuvo un error propio"),
        (418, "El sitio rechazó la consulta (HTTP 418)."),
    ],
)
def test_http_errors_say_what_happened_in_plain_words(
    conn, rules, make_client, status, start
) -> None:
    client = make_client(lambda _: httpx.Response(status, json={}))
    report = run_source(WorkdaySource(client, WORKDAY), conn, rules)
    assert report.error.startswith(start)
    assert report.error.endswith(f"[HTTP {status} · acme.wd1.myworkdayjobs.com]")
    assert "developer.mozilla.org" not in report.error


def test_workday_skips_postings_without_link(load_fixture, make_client) -> None:
    page = load_fixture("workday_page.json")
    page["jobPostings"].append({"title": "Placeholder", "bulletFields": ["R0004"]})

    source = WorkdaySource(make_client(lambda _: httpx.Response(200, json=page)), WORKDAY)
    assert [j.ats_job_id for j in source.fetch()] == ["acme:R0001", "acme:R0002", "acme:R0003"]
