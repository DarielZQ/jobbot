"""Job-board sources: Amazon, Get on Board, Remotive, Jobicy, Himalayas and Recruitee.

No network: httpx.MockTransport.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

import httpx

from conftest import make_job
from jobbot.config import (
    AmazonTarget,
    GetOnBoardTarget,
    HimalayasTarget,
    JobicyTarget,
    RecruiteeTarget,
    RemotiveTarget,
)
from jobbot.core import db
from jobbot.core.models import Job
from jobbot.core.state import Status
from jobbot.discovery.amazon import AmazonSource
from jobbot.discovery.base import Source
from jobbot.discovery.getonboard import GetOnBoardSource
from jobbot.discovery.himalayas import HimalayasSource
from jobbot.discovery.jobicy import JobicySource
from jobbot.discovery.pipeline import run_source
from jobbot.discovery.recruitee import RecruiteeSource
from jobbot.discovery.remotive import RemotiveSource


def _serve(payload: object, urls: list[str] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if urls is not None:
            urls.append(str(request.url))
        return httpx.Response(200, json=payload)

    return handler


def test_amazon_source(load_fixture, make_client, rules) -> None:
    urls: list[str] = []
    client = make_client(_serve(load_fixture("amazon_search.json"), urls))
    support, consultant = AmazonSource(
        client, AmazonTarget(country_code="CRI", country="Costa Rica")
    ).fetch()

    assert len(urls) == 1  # hits=2 fit in one page
    assert "normalized_country_code%5B%5D=CRI" in urls[0]
    assert support.ats_job_id == "10576514"
    assert support.location == "San Jose, San Jose, CRI, Costa Rica"
    assert support.url.startswith("https://www.amazon.jobs/en/jobs/10576514/")
    assert support.posted_at == datetime(2026, 10, 20)
    # Preferred qualifications are left out so "3+ years" there does not reject the job.
    assert "3+ years" not in support.description
    assert rules.evaluate(support).ok
    assert consultant.title == "ACM Consultant (S), US Accommodations"
    assert consultant.location == "CRI, Costa Rica"
    assert consultant.posted_at is None


def test_getonboard_source_maps_remote_modality_and_seniority(
    load_fixture, make_client, rules
) -> None:
    urls: list[str] = []
    client = make_client(_serve(load_fixture("getonboard_search.json"), urls))
    target = GetOnBoardTarget(queries=["support", "soporte"], max_pages=3)
    jobs = list(GetOnBoardSource(client, target).fetch())

    assert len(urls) == 2  # one page per query (total_pages=1)
    assert len(jobs) == 2  # the second query returns the same ids: deduplicated
    remote, local = jobs
    assert (remote.company, remote.location, remote.remote) == (
        "Acme LATAM",
        "Remote - LATAM (fully remote)",
        True,
    )
    assert remote.description.startswith("Seniority: Junior.")
    assert rules.evaluate(remote).ok
    assert local.location == "Chile (remote, must live in country)"
    assert local.url == "https://www.getonbrd.com/jobs/soporte-ti-semi-senior-beta-santiago"
    assert not rules.evaluate(local).ok


def test_getonboard_senior_rejected_but_semi_senior_passes(rules) -> None:
    def job(seniority: str):
        return make_job(
            title="Technical Support Specialist",
            location="Remote - LATAM (fully remote)",
            remote=True,
            description=f"Seniority: {seniority}.\nGreat team.",
        )

    result = rules.evaluate(job("Senior"))
    assert (result.ok, result.reason) == (False, "description_excluded: seniority senior")
    assert rules.evaluate(job("Semi Senior")).ok  # level 2 passes


def test_remotive_source(load_fixture, make_client, rules) -> None:
    urls: list[str] = []
    client = make_client(_serve(load_fixture("remotive_jobs.json"), urls))
    target = RemotiveTarget(categories=["customer-support", "data"])
    latam, usa = RemotiveSource(client, target).fetch()

    assert urls[0] == "https://remotive.com/api/remote-jobs?category=customer-support"
    assert latam.location == "Remote - LATAM" and latam.remote
    assert rules.evaluate(latam).ok
    assert rules.evaluate(usa).reason == "remote_region_unknown"


def test_jobicy_source(load_fixture, make_client, rules) -> None:
    urls: list[str] = []
    client = make_client(_serve(load_fixture("jobicy_jobs.json"), urls))
    database, bilingual, senior, brazil = JobicySource(
        client, JobicyTarget(geo="costa-rica")
    ).fetch()

    assert urls == ["https://jobicy.com/api/jobs?count=200&geo=costa-rica"]  # nextCursor null
    assert database.ats_job_id == "900101" and database.remote
    assert database.location == "Remote - LATAM, Canada, USA"
    assert database.url.startswith("https://jobicy.com/jobs/900101")  # Jobicy stays the source
    assert database.posted_at == datetime(2026, 10, 26, 4, 15, 18, tzinfo=UTC)
    assert rules.evaluate(database).ok
    assert rules.evaluate(bilingual).ok  # jobLevel "Any"
    assert rules.evaluate(senior).reason.startswith("description_excluded: seniority senior")
    assert rules.evaluate(brazil).reason == "remote_region_unknown"  # Brazil only


def test_jobicy_follows_the_cursor(make_client) -> None:
    pages = [
        {"jobs": [{"id": 1, "jobTitle": "Help Desk"}], "nextCursor": "abc=="},
        {"jobs": [{"id": 2, "jobTitle": "Service Desk"}], "nextCursor": None},
    ]
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, json=pages[len(urls) - 1])

    jobs = list(JobicySource(make_client(handler), JobicyTarget(geo="costa-rica")).fetch())
    assert [j.title for j in jobs] == ["Help Desk", "Service Desk"]
    assert urls[1].endswith("&cursor=abc%3D%3D")


def test_himalayas_source(load_fixture, make_client, rules_any_age) -> None:
    rules = rules_any_age
    urls: list[str] = []
    payload = load_fixture("himalayas_search.json")

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, json=payload if "page=1" in str(request.url) else {"jobs": []})

    target = HimalayasTarget(
        queries=["help desk", "support"], max_pages=3, country="Costa Rica", utc_offset=-6
    )
    jobs = list(HimalayasSource(make_client(handler), target).fetch())

    # Two pages per query: the second one is empty. The second query repeats the same jobs.
    assert len(urls) == 4
    assert (
        urls[0] == "https://himalayas.app/jobs/api/search?q=help%20desk&country=Costa%20Rica&page=1"
    )
    # The edited Germany/UTC+1 job is not open to Costa Rica.
    central, worldwide, senior = jobs
    assert central.location == "Remote - Costa Rica" and central.remote
    assert central.url.endswith("?utm_source=api")  # applicationLink, unchanged
    assert central.posted_at == datetime.fromtimestamp(1788925405, UTC)
    assert rules.evaluate(central).ok
    assert worldwide.location == "Remote - Worldwide"
    assert rules.evaluate(worldwide).ok
    assert senior.description.startswith("Seniority: Senior.")  # only "Senior" listed
    assert not rules.evaluate(senior).ok


def test_recruitee_source(load_fixture, make_client, rules_any_age) -> None:
    rules = rules_any_age
    client = make_client(_serve(load_fixture("recruitee_offers.json")))
    target = RecruiteeTarget(company="Globex Soporte S.A.", subdomain="globex1")
    heredia, mexico = RecruiteeSource(client, target).fetch()

    assert heredia.ats_job_id == "globex1:7001"
    assert heredia.posted_at == datetime(2026, 10, 1, 12, 34, 56, tzinfo=UTC)
    assert "1 año de experiencia" in heredia.description
    assert rules.evaluate(heredia).ok
    assert mexico.location == "Remote in Mexico"
    assert not rules.evaluate(mexico).ok


class _CountingSource(Source):
    name = "remotive"
    min_hours_between_runs = 6

    def __init__(self) -> None:
        self.calls = 0

    def fetch(self) -> Iterable[Job]:
        self.calls += 1
        return [
            make_job(
                source=self.name,
                ats="remotive",
                ats_job_id="1",
                location="Remote - LATAM",
                remote=True,
            )
        ]


def test_pipeline_respects_min_hours_between_runs(conn, rules) -> None:
    source = _CountingSource()
    assert run_source(source, conn, rules).new_matched == 1

    report = run_source(source, conn, rules)  # immediately again: skipped
    assert report.skipped_recent and source.calls == 1

    old = (datetime.now(UTC) - timedelta(hours=7)).isoformat(timespec="seconds")
    conn.execute("UPDATE jobs SET last_seen_at = ?", (old,))
    assert run_source(source, conn, rules).seen == 1
    assert source.calls == 2
    assert db.list_jobs(conn, status=Status.DISCOVERED)[0].role_family == "it_support"
