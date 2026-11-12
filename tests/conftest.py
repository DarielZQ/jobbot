from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from jobbot.config import load_search_rules
from jobbot.core import db
from jobbot.core.http import HttpClient
from jobbot.core.models import Job
from jobbot.initialize import init_home
from jobbot.matching.rules import RuleSet

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def home(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every test gets its own data folder, made by `jobbot init` with the Costa Rica preset and
    the fictitious example profile: no test ever reads the real user's files."""
    folder = tmp_path_factory.mktemp("home") / "JobBot"
    init_home("costa-rica-it", folder)
    monkeypatch.setenv("JOBBOT_HOME", str(folder))
    return folder


@pytest.fixture
def rules() -> RuleSet:
    # The shipped preset: the tests also guard the filters users start with.
    return RuleSet(load_search_rules())


@pytest.fixture
def rules_any_age() -> RuleSet:
    """The preset without its age limit, for fixtures with fixed past dates (the limit has
    tests of its own)."""
    search = load_search_rules()
    search.max_age_days = 0
    return RuleSet(search)


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def load_fixture() -> Callable[[str], object]:
    def _load(name: str) -> object:
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    return _load


@pytest.fixture
def make_client() -> Callable[[Callable[[httpx.Request], httpx.Response]], HttpClient]:
    def _make(handler: Callable[[httpx.Request], httpx.Response]) -> HttpClient:
        return HttpClient(transport=httpx.MockTransport(handler), sleep=lambda _: None)

    return _make


def make_job(**overrides: object) -> Job:
    defaults: dict[str, object] = {
        "source": "test",
        "ats": "test",
        "ats_job_id": "1",
        "company": "Acme",
        "title": "IT Support Analyst",
        "location": "Heredia, Costa Rica",
        "url": "https://example.com/1",
    }
    return Job(**{**defaults, **overrides})
