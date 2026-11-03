"""Check a Workday career site before adding it to config/targets.yaml.

Usage:
    uv run python scripts/probe_workday.py https://intel.wd1.myworkdayjobs.com/External [...]

Prints the targets.yaml entry and how many postings the country facet finds.
"""

from __future__ import annotations

import sys
from urllib.parse import urlsplit

import httpx

from jobbot.config import WorkdayTarget
from jobbot.core.http import HttpClient
from jobbot.discovery.workday import PAGE_SIZE, find_country_facet


def parse_url(url: str) -> WorkdayTarget:
    parts = urlsplit(url)
    segments = [s for s in parts.path.split("/") if s]
    # Optional locale segment: /en-US/External
    if segments and len(segments[0]) == 5 and segments[0][2] == "-":
        segments = segments[1:]
    if not segments:
        raise ValueError(f"No site segment in {url}")
    host = parts.netloc
    return WorkdayTarget(
        company=host.split(".")[0], host=host, tenant=host.split(".")[0], site=segments[0]
    )


def probe(client: HttpClient, target: WorkdayTarget) -> None:
    api = f"https://{target.host}/wday/cxs/{target.tenant}/{target.site}/jobs"
    payload = {"appliedFacets": {}, "limit": PAGE_SIZE, "offset": 0, "searchText": ""}
    data = client.post_json(api, payload)
    facet = find_country_facet(data.get("facets", []), target.country)
    print(f"\n{target.host}/{target.site}: {data.get('total')} vacantes en total")
    if facet is None:
        print(f"  Sin faceta para '{target.country}'.")
        return
    parameter, ids = facet
    filtered = client.post_json(api, {**payload, "appliedFacets": {parameter: ids}})
    count = filtered.get("total")
    print(f"  Faceta {parameter} ({len(ids)} valores): {count} vacantes en {target.country}")
    print("  Entrada para config/targets.yaml:")
    print(
        f'    - {{ company: "{target.company}", host: {target.host}, '
        f"tenant: {target.tenant}, site: {target.site} }}"
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    with HttpClient(min_interval_s=1.0, max_retries=0) as client:
        for url in sys.argv[1:]:
            try:
                probe(client, parse_url(url))
            except (httpx.HTTPError, ValueError) as exc:
                print(f"\n{url}: FALLA {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
