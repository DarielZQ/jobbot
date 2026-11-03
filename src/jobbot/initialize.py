"""`jobbot init`: create the user's data folder from the templates (ADR-019).

A preset is a folder of config files for one kind of search (`templates/presets/<name>/`). The
profile templates are fictitious examples the user replaces. Existing files are never
overwritten, so running it again only fills in what is missing.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from jobbot import paths

PRESETS_DIR = paths.TEMPLATES_DIR / "presets"


def presets() -> list[str]:
    return sorted(p.name for p in PRESETS_DIR.iterdir() if p.is_dir())


def init_home(preset: str, home: Path | None = None) -> list[Path]:
    """Copy the preset config, the example profile and the .env template. Returns new files."""
    if preset not in presets():
        raise ValueError(preset)
    home = home or paths.home()
    profile = paths.TEMPLATES_DIR / "profile"
    pairs = [(f, home / "config" / f.name) for f in sorted((PRESETS_DIR / preset).glob("*.yaml"))]
    for template in sorted(profile.rglob("*.yaml")):
        pairs.append((template, home / "profile" / template.relative_to(profile)))
    pairs.append((paths.TEMPLATES_DIR / "env", home / ".env"))

    created = []
    for source, target in pairs:
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        created.append(target)
    (home / "data").mkdir(parents=True, exist_ok=True)
    return created


def is_initialized(home: Path | None = None) -> bool:
    return ((home or paths.home()) / "config" / "search.yaml").exists()
