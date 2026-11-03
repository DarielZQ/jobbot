"""Where the user's data lives (ADR-019).

Everything personal sits in one folder outside the code: JOBBOT_HOME, or a visible `JobBot`
folder in the user's home by default. The repository only ships templates
(`jobbot/templates/`), copied there by `jobbot init`.

    <home>/config/   settings.yaml, search.yaml, targets.yaml
    <home>/profile/  facts.yaml, answers.yaml, resumes/, private/ (contact, Gmail token)
    <home>/data/     jobbot.db, reports/, logs/
    <home>/.env      JOBBOT_CONTACT_EMAIL and other secrets

Paths are computed on every call, so a test (or a second instance) can point JOBBOT_HOME
somewhere else at run time.
"""

from __future__ import annotations

import os
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
DEFAULT_FOLDER = "JobBot"


def home() -> Path:
    value = os.environ.get("JOBBOT_HOME", "").strip()
    folder = Path(value).expanduser() if value else Path.home() / DEFAULT_FOLDER
    return folder.resolve()


def config_dir() -> Path:
    return home() / "config"


def profile_dir() -> Path:
    return home() / "profile"


def resumes_dir() -> Path:
    return profile_dir() / "resumes"


def data_dir() -> Path:
    return home() / "data"


def reports_dir() -> Path:
    return data_dir() / "reports"


def logs_dir() -> Path:
    return data_dir() / "logs"


def resolve(path: Path) -> Path:
    """A path from the config: relative ones are inside the data folder."""
    return path if path.is_absolute() else home() / path


def shown(path: Path) -> str:
    """For messages: relative to the data folder when inside it, absolute otherwise."""
    try:
        return str(path.relative_to(home()))
    except ValueError:
        return str(path)
