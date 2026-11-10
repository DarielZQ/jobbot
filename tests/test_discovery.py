from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime

import httpx

from conftest import FIXTURES, make_job
from jobbot.config import (
    AshbyTarget,
    DeelTarget,
    GreenhouseTarget,
    LeverTarget,
    SuccessFactorsTarget,
    WorkdayTarget,
)
from jobbot.core import db
from jobbot.core.models import Job
from jobbot.core.state import Status
from jobbot.discovery.ashby import AshbySource
from jobbot.discovery.base import Source
from jobbot.discovery.deel import DeelSource
from jobbot.discovery.greenhouse import GreenhouseSource
from jobbot.discovery.lever import LeverSource
from jobbot.discovery.pipeline import run_source
from jobbot.discovery.successfactors import SuccessFactorsSource
from jobbot.discovery.workday import WorkdaySource, find_country_facet

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


def test_lever_source(load_fixture, make_client) -> None:
    payload = load_fixture("lever_postings.json")
    client = make_client(lambda request: httpx.Response(200, json=payload))
    (job,) = LeverSource(client, LeverTarget(company="Acme", slug="acme")).fetch()

    assert job.title == "Cloud Support Associate"
    assert job.location == "San José, Costa Rica"
    assert "3+ years" in job.description


def test_successfactors_source(make_client) -> None:
    xml = (FIXTURES / "successfactors_rss.xml").read_text(encoding="utf-8")
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(200, text=xml)

    target = SuccessFactorsTarget(
        company="Acme", base_url="https://jobs.acme.com/", keywords="costa rica"
    )
    first, second = SuccessFactorsSource(make_client(handler), target).fetch()

    assert seen_urls == [
        "https://jobs.acme.com/services/rss/job/?locale=en_US&keywords=costa%20rica"
    ]
    assert first.title == "Junior Networking Agent - Audio Products (Entry Level) (On Site)"
    assert first.location == "Heredia, Costa Rica, CR"
    assert first.url == "https://jobs.acme.com/job/Heredia-Junior-Networking-Agent/1413280300/"
    assert first.ats_job_id == "jobs.acme.com:1413280300"
    assert first.posted_at is not None
    # A parenthesis without commas is part of the title, not a location.
    assert (second.title, second.location) == (
        "Remote Customer Service Representative (Remote)",
        "",
    )
    assert second.remote


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
    assert report.error.startswith("ConnectError")


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
    assert report.error.startswith("HTTPStatusError: Client error '403 Forbidden'")
    assert report.error.endswith("(Mail not enabled)")


def test_pipeline_reports_unexpected_errors_instead_of_stopping(conn, rules) -> None:
    class Odd(Source):
        name = "odd"

        def __init__(self) -> None:
            pass

        def fetch(self) -> Iterable[Job]:
            yield make_job()
            raise KeyError("externalPath")

    report = run_source(Odd(), conn, rules)
    assert report.error == "KeyError: 'externalPath'"
    assert report.new_matched + report.new_skipped == 1  # what came before the error is kept


def test_workday_skips_postings_without_link(load_fixture, make_client) -> None:
    page = load_fixture("workday_page.json")
    page["jobPostings"].append({"title": "Placeholder", "bulletFields": ["R0004"]})

    source = WorkdaySource(make_client(lambda _: httpx.Response(200, json=page)), WORKDAY)
    assert [j.ats_job_id for j in source.fetch()] == ["acme:R0001", "acme:R0002", "acme:R0003"]
