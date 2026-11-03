"""Resume generation: profile/resumes/<variant>.yaml -> HTML -> PDF (Chromium via Playwright).

Everything lives in the user's data folder (`jobbot.paths`): PDFs land next to their YAML as
<variant>_<lang>.pdf, and contact data comes from profile/private/contact.yaml.
`profile/resumes/checks.yaml` lists claims a CV must never make (or must make): a PDF that
breaks them is not generated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

from jobbot import paths

LANGS = ("es", "en")
SUMMARY_TITLE = {"es": "Perfil profesional", "en": "Professional summary"}
CHECKS_FILE = "checks.yaml"
_PAGE_MARKER = re.compile(rb"/Type\s*/Page(?!s)")


@dataclass(frozen=True)
class BuiltResume:
    path: Path
    pages: int


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def variants() -> list[str]:
    return sorted(p.stem for p in paths.resumes_dir().glob("*.yaml") if p.name != CHECKS_FILE)


def load_content(variant: str) -> dict:
    return _read_yaml(paths.resumes_dir() / f"{variant}.yaml")


def _texts(node: object) -> list[str]:
    """Every string inside a CV's content, in reading order."""
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [t for value in node.values() for t in _texts(value)]
    if isinstance(node, list):
        return [t for item in node for t in _texts(item)]
    return []


def check_content(content: dict, checks: dict | None = None) -> list[str]:
    """Problems of one CV language against checks.yaml: forbidden claims made, required missing."""
    if checks is None:
        checks = _read_yaml(paths.resumes_dir() / CHECKS_FILE)
    text = "\n".join(_texts(content))
    problems = []
    for rule in checks.get("forbidden") or []:
        if match := re.search(rule["pattern"], text, re.I):
            problems.append(f"«{match.group(0)}»: {rule.get('reason') or 'frase prohibida'}")
    for rule in checks.get("required") or []:
        if not re.search(rule["pattern"], text, re.I):
            problems.append(f"falta {rule['pattern']}: {rule.get('reason') or 'frase obligatoria'}")
    return problems


def _contact_line() -> str:
    facts = _read_yaml(paths.profile_dir() / "facts.yaml")
    contact = _read_yaml(paths.profile_dir() / "private" / "contact.yaml")
    location = facts.get("identity", {}).get("location", {})
    place = ", ".join(filter(None, [location.get("city"), location.get("province")]))
    country = location.get("country", "")
    parts = [f"{place}, {country}" if place else country]
    parts += [contact.get("phone"), contact.get("email")]
    linkedin = (contact.get("linkedin_url") or "").removeprefix("https://").removeprefix("www.")
    parts.append(linkedin)
    return " · ".join(p for p in parts if p)


def render_html(variant: str, lang: str) -> str:
    facts = _read_yaml(paths.profile_dir() / "facts.yaml")
    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent),
        autoescape=select_autoescape(["html", "j2"]),
    )
    template = env.get_template("template.html.j2")
    return template.render(
        lang=lang,
        name=facts.get("identity", {}).get("name", ""),
        c=load_content(variant)[lang],
        contact_line=_contact_line(),
        summary_title=SUMMARY_TITLE[lang],
    )


def count_pages(pdf: bytes) -> int:
    return len(_PAGE_MARKER.findall(pdf))


def page_note(pages: int, max_pages: int) -> str:
    """Nothing for one page, a plain note up to the limit, a warning past it."""
    if pages > max_pages:
        return f"AVISO: {pages} páginas (máximo: {max_pages})"
    return f"{pages} páginas" if pages > 1 else ""


class ResumeCheckFailed(Exception):
    """A CV breaks profile/resumes/checks.yaml; nothing was generated."""


def build(selected_variants: list[str], langs: list[str]) -> list[BuiltResume]:
    """Raises ResumeCheckFailed before opening the browser if any CV breaks checks.yaml, and
    ImportError when the "resumes" extra (Playwright) is not installed."""
    problems = [
        f"{variant} ({lang}) {problem}"
        for variant in selected_variants
        for lang in langs
        for problem in check_content(load_content(variant).get(lang) or {})
    ]
    if problems:
        raise ResumeCheckFailed("\n".join(problems))

    from playwright.sync_api import sync_playwright

    built: list[BuiltResume] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        for variant in selected_variants:
            for lang in langs:
                page.set_content(render_html(variant, lang), wait_until="load")
                pdf = page.pdf(format="Letter", print_background=True, prefer_css_page_size=True)
                path = paths.resumes_dir() / f"{variant}_{lang}.pdf"
                path.write_bytes(pdf)
                built.append(BuiltResume(path, count_pages(pdf)))
        browser.close()
    return built
