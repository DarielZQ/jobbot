"""The data folder (JOBBOT_HOME), `jobbot init`, presets and the `region` block."""

from __future__ import annotations

from pathlib import Path

import pytest

from jobbot import cli, initialize, paths
from jobbot.config import (
    AmazonTarget,
    HimalayasTarget,
    Region,
    Targets,
    WorkdayTarget,
    load_settings,
    load_targets,
    with_region,
)
from jobbot.discovery.base import SourceNotConfigured
from jobbot.discovery.himalayas import HimalayasSource


def test_home_comes_from_jobbot_home_or_defaults_to_a_visible_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JOBBOT_HOME", str(tmp_path / "datos"))
    assert paths.home() == (tmp_path / "datos").resolve()
    assert paths.resumes_dir() == (tmp_path / "datos" / "profile" / "resumes").resolve()

    monkeypatch.delenv("JOBBOT_HOME")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert paths.home() == (tmp_path / "JobBot").resolve()


def test_shown_paths_are_relative_inside_home_and_absolute_outside(home: Path) -> None:
    assert paths.shown(home / "data" / "jobbot.db") == str(Path("data") / "jobbot.db")
    outside = home.parent / "elsewhere.txt"
    assert paths.shown(outside) == str(outside)


def test_init_copies_preset_and_example_profile_without_overwriting(tmp_path: Path) -> None:
    folder = tmp_path / "nuevo"
    created = initialize.init_home("remote-latam", folder)

    names = {p.relative_to(folder).as_posix() for p in created}
    assert {"config/settings.yaml", "config/search.yaml", "config/targets.yaml"} <= names
    assert {"profile/facts.yaml", "profile/resumes/checks.yaml", ".env"} <= names
    assert (folder / "data").is_dir()

    (folder / "config" / "search.yaml").write_text("# mío\n", encoding="utf-8")
    assert initialize.init_home("costa-rica-it", folder) == []  # nothing is overwritten
    assert (folder / "config" / "search.yaml").read_text(encoding="utf-8") == "# mío\n"


def test_unknown_preset_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        initialize.init_home("marte", tmp_path)


def test_commands_ask_for_init_when_there_is_no_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("JOBBOT_HOME", str(tmp_path / "vacío"))
    assert cli.main(["stats"]) == 2
    assert "jobbot init" in capsys.readouterr().out


def test_costa_rica_preset_fills_every_source_country_from_region() -> None:
    region = load_settings().region
    targets = load_targets()

    assert (region.country, region.country_code, region.utc_offset) == ("Costa Rica", "CRI", -6)
    assert {t.country for t in targets.workday} == {"Costa Rica"}
    assert {t.country_code for t in targets.amazon} == {"CRI"}
    assert {t.keywords for t in targets.successfactors} == {"costa rica"}
    assert targets.jobicy.geo == "costa-rica"
    assert (targets.himalayas.country, targets.himalayas.utc_offset) == ("Costa Rica", -6)
    assert targets.email_alerts is not None and not targets.email_alerts.enabled


def test_an_explicit_country_in_a_source_wins_over_region() -> None:
    targets = Targets(
        workday=[WorkdayTarget(company="A", host="a", tenant="a", site="s", country="Panamá")],
        amazon=[AmazonTarget()],
    )
    with_region(targets, Region(country="Costa Rica", country_code="CRI"))
    assert targets.workday[0].country == "Panamá"
    assert targets.amazon[0].country_code == "CRI"


def test_country_sources_say_what_is_missing_instead_of_guessing(make_client) -> None:
    source = HimalayasSource(make_client(lambda request: None), HimalayasTarget(queries=["it"]))
    with pytest.raises(SourceNotConfigured, match="region"):
        list(source.fetch())
