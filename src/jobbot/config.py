"""Load and validate the user's config/*.yaml (in the data folder, see `jobbot.paths`)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from jobbot import paths


class HttpSettings(BaseModel):
    timeout_s: float = 30
    min_interval_s: float = 2.0
    max_retries: int = 3
    # Per-host override, e.g. the Gmail API tolerates much faster calls than career sites.
    host_min_interval_s: dict[str, float] = Field(default_factory=dict)


class NotificationSettings(BaseModel):
    windows_toast: bool = True  # Windows only; ignored elsewhere


class Region(BaseModel):
    """Where the user looks for work. Sources use it unless their own entry says otherwise."""

    country: str = ""  # as job sites write it, e.g. "Costa Rica"
    country_code: str = ""  # ISO 3166-1 alpha-3, e.g. "CRI"
    country_slug: str = ""  # e.g. "costa-rica" (Jobicy)
    utc_offset: float | None = None  # standard offset; many remote jobs restrict by time zone
    timezone: str = ""  # IANA name, e.g. "America/Costa_Rica"


class PanelSettings(BaseModel):
    port: int = 8765


class ResumeSettings(BaseModel):
    max_pages: int = 2


class Paths(BaseModel):
    db: Path = Path("data/jobbot.db")


class Settings(BaseModel):
    region: Region = Region()
    paths: Paths = Paths()
    http: HttpSettings = HttpSettings()
    notifications: NotificationSettings = NotificationSettings()
    panel: PanelSettings = PanelSettings()
    resumes: ResumeSettings = ResumeSettings()
    # Source names (as in the report, e.g. "workday:intel") that searches skip
    disabled_sources: list[str] = Field(default_factory=list)

    def db_path(self) -> Path:
        return paths.resolve(self.paths.db)


class RoleFamily(BaseModel):
    label: str = ""  # shown in the report and the panel; the family key if empty
    priority: Literal["primary", "secondary"] = "primary"
    cv: str = Field(default="", description="Resume prefix in profile/resumes/")
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)


class TitleRules(BaseModel):
    exclude: list[str] = Field(default_factory=list)


class DescriptionRules(BaseModel):
    exclude: list[str] = Field(default_factory=list)
    # Seniority labels some boards put in the description: they exclude a posting unless it
    # was posted less than `fresh_hours` before it was seen (ADR-020)
    seniority: list[str] = Field(default_factory=list)


class LocationRules(BaseModel):
    # Places where on-site and hybrid jobs are acceptable, and places inside them that are not.
    local: list[str] = Field(default_factory=list)
    local_exclude: list[str] = Field(default_factory=list)
    remote_ok: list[str] = Field(default_factory=list)
    remote_reject: list[str] = Field(default_factory=list)


class SearchRules(BaseModel):
    # A posting is fresh when it was posted less than this many hours ago (ADR-020)
    fresh_hours: float = 24
    # Jobs posted (or, without a date, first seen) longer ago than this are discarded, also once
    # they are pending; 0 = no limit (ADR-023)
    max_age_days: int = 0
    role_families: dict[str, RoleFamily] = Field(default_factory=dict)
    # Companies where any role will do: their jobs pass without a role family; title.exclude,
    # location and description rules still apply (ADR-022)
    any_role_companies: list[str] = Field(default_factory=list)
    title: TitleRules = TitleRules()
    description: DescriptionRules = DescriptionRules()
    location: LocationRules = LocationRules()


class WorkdayTarget(BaseModel):
    company: str
    host: str = Field(description="e.g. intel.wd1.myworkdayjobs.com")
    tenant: str
    site: str
    country: str = ""  # from settings.yaml `region` unless set here


class GreenhouseTarget(BaseModel):
    company: str
    token: str
    # What a bare "Remote" means at this company, e.g. "Worldwide" (ADR-021)
    remote_scope: str = ""


class LeverTarget(BaseModel):
    company: str
    slug: str


class AshbyTarget(BaseModel):
    company: str
    board: str = Field(description="jobs.ashbyhq.com/<board>")
    remote_scope: str = ""  # as in GreenhouseTarget


class SuccessFactorsTarget(BaseModel):
    company: str
    base_url: str = Field(description="Career Site Builder root, e.g. https://jobs.foundever.com")
    keywords: str = ""  # RSS search; the region country unless set here
    locale: str = "en_US"


class AmazonTarget(BaseModel):
    company: str = "Amazon"
    country_code: str = ""  # ISO alpha-3; from `region` unless set here
    country: str = ""


class RecruiteeTarget(BaseModel):
    company: str
    subdomain: str = Field(description="<subdomain>.recruitee.com")


class GetOnBoardTarget(BaseModel):
    queries: list[str] = Field(default_factory=list)
    max_pages: int = 2


class RemotiveTarget(BaseModel):
    categories: list[str] = Field(default_factory=list)
    # Remotive's terms ask for at most 4 requests a day.
    min_hours_between_runs: float = 6


class JobicyTarget(BaseModel):
    # Eligibility slug from https://jobicy.com/api/jobs?get=locations. A country slug also returns
    # the Anywhere and LATAM listings.
    geo: str = ""  # from `region.country_slug` unless set here
    # Jobicy's fair use: no new polling pass more often than once an hour.
    min_hours_between_runs: float = 1


class HimalayasTarget(BaseModel):
    # Name as Himalayas writes it in locationRestrictions (the search accepts it too).
    country: str = ""  # from `region` unless set here
    # Standard UTC offset of that country: many jobs are restricted by time zone.
    utc_offset: float | None = None
    queries: list[str] = Field(default_factory=list)
    max_pages: int = 2
    # Requests without an API key share one public allowance: query rarely.
    min_hours_between_runs: float = 6


class ElempleoTarget(BaseModel):
    # Search slugs after https://www.elempleo.com/cr/ofertas-empleo/
    searches: list[str] = Field(default_factory=list)
    min_hours_between_runs: float = 12


class ICimsTarget(BaseModel):
    company: str
    host: str = Field(description="e.g. jobs-<company>.icims.com")
    # What follows /jobs/search?ss=1& once the portal is filtered, e.g. searchLocation=<id>-<Place>
    search: str = ""


class DeelTarget(BaseModel):
    # Its own careers page: every listed job with the countries it can be done from (ADR-021)
    url: str = "https://www.deel.com/careers/"
    min_hours_between_runs: float = 12  # the page weighs over 1 MB


class JibeTarget(BaseModel):
    company: str
    host: str = Field(description="e.g. <company>.jibeapply.com")
    country: str = ""  # from `region` unless set here


class EmailAlertFeed(BaseModel):
    query: str = Field(description="Gmail search, e.g. from:(jobalerts-noreply@linkedin.com)")
    # Used when the email does not say where the job is (the alert was set up for one place).
    default_location: str = ""
    # What a bare "Remote" means in this feed, e.g. "Worldwide" for a site that only sends jobs
    # it matched to the candidate's country (Torre)
    remote_scope: str = ""


class EmailAlertsTarget(BaseModel):
    # Off until the user sets up Gmail (extra "gmail"); otherwise every run would warn about it.
    enabled: bool = False
    credentials_file: Path = Path("profile/private/gmail_credentials.json")
    token_file: Path = Path("profile/private/gmail_token.json")
    lookback_days: int = 14
    max_messages: int = 50
    linkedin: EmailAlertFeed | None = None
    computrabajo: EmailAlertFeed | None = None
    indeed: EmailAlertFeed | None = None
    elempleo: EmailAlertFeed | None = None
    torre: EmailAlertFeed | None = None
    # Gmail query per site whose application confirmations mark jobs as applied (ADR-018)
    confirmations: dict[str, str] = Field(default_factory=dict)


class LinkedInSearches(BaseModel):
    """Links to LinkedIn's own job search, last `fresh_hours`, newest first (ADR-020). JobBot
    never opens them: the candidate does, in their browser (ADR-005)."""

    label: str = ""  # shown before the buttons, e.g. "Latinoamérica remoto"; the place if empty
    keywords: list[str] = Field(default_factory=list)
    geo_id: str = ""  # LinkedIn's id for the place, e.g. 101739942 (Costa Rica)
    location: str = ""  # from `region.country` unless set here
    remote_only: bool = False  # LinkedIn's "En remoto" filter (ADR-023)


class Targets(BaseModel):
    workday: list[WorkdayTarget] = Field(default_factory=list)
    greenhouse: list[GreenhouseTarget] = Field(default_factory=list)
    lever: list[LeverTarget] = Field(default_factory=list)
    ashby: list[AshbyTarget] = Field(default_factory=list)
    successfactors: list[SuccessFactorsTarget] = Field(default_factory=list)
    amazon: list[AmazonTarget] = Field(default_factory=list)
    recruitee: list[RecruiteeTarget] = Field(default_factory=list)
    icims: list[ICimsTarget] = Field(default_factory=list)
    getonboard: GetOnBoardTarget | None = None
    remotive: RemotiveTarget | None = None
    jobicy: JobicyTarget | None = None
    himalayas: HimalayasTarget | None = None
    elempleo: ElempleoTarget | None = None
    deel: DeelTarget | None = None
    jibe: list[JibeTarget] = Field(default_factory=list)
    email_alerts: EmailAlertsTarget | None = None
    # One group of buttons per entry; a single mapping (the first format) is one group
    linkedin_searches: list[LinkedInSearches] = Field(default_factory=list)

    @field_validator("linkedin_searches", mode="before")
    @classmethod
    def _one_or_many(cls, value: object) -> object:
        return [value] if isinstance(value, dict) else value or []


resolve = paths.resolve


def _load_yaml(name: str, config_dir: Path | None) -> dict:
    path = (config_dir or paths.config_dir()) / name
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_settings(config_dir: Path | None = None) -> Settings:
    return Settings.model_validate(_load_yaml("settings.yaml", config_dir))


def load_search_rules(config_dir: Path | None = None) -> SearchRules:
    return SearchRules.model_validate(_load_yaml("search.yaml", config_dir))


def load_targets(config_dir: Path | None = None) -> Targets:
    targets = Targets.model_validate(_load_yaml("targets.yaml", config_dir))
    return with_region(targets, load_settings(config_dir).region)


def _fill(target: BaseModel, **values: object) -> None:
    """Set the fields the user's own entry left out (explicit values always win)."""
    for name, value in values.items():
        if name not in target.model_fields_set and value not in ("", None):
            setattr(target, name, value)


def with_region(targets: Targets, region: Region) -> Targets:
    """Sources take the country from `region` unless their entry names one."""
    for target in [*targets.workday, *targets.jibe]:
        _fill(target, country=region.country)
    for target in targets.amazon:
        _fill(target, country_code=region.country_code, country=region.country)
    for target in targets.successfactors:
        _fill(target, keywords=region.country.lower())
    if targets.jobicy:
        _fill(targets.jobicy, geo=region.country_slug)
    if targets.himalayas:
        _fill(targets.himalayas, country=region.country, utc_offset=region.utc_offset)
    for searches in targets.linkedin_searches:
        _fill(searches, location=region.country)
    return targets
