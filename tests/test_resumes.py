"""Resume rendering and the per-user CV checks (profile/resumes/checks.yaml).

Runs on the fictitious example profile that `jobbot init` copies (see conftest.home).
"""

from __future__ import annotations

import pytest

from jobbot import paths, resumes


def test_example_profile_ships_both_variants_and_no_checks_variant() -> None:
    assert resumes.variants() == ["data-ai", "it-support"]


@pytest.mark.parametrize("variant", ["data-ai", "it-support"])
@pytest.mark.parametrize("lang", resumes.LANGS)
def test_resume_renders_core_sections(variant: str, lang: str) -> None:
    html = resumes.render_html(variant, lang)
    assert "Alex Ejemplo" in html
    assert "Acme Corp" in html
    assert "dariel@example.invalid" in html  # contact line from profile/private/contact.yaml
    assert "ITIL 4 Foundation" in html
    assert "built-in method" not in html  # template must read dict keys, not dict methods


@pytest.mark.parametrize("variant", ["data-ai", "it-support"])
@pytest.mark.parametrize("lang", resumes.LANGS)
def test_example_resumes_pass_the_example_checks(variant: str, lang: str) -> None:
    assert resumes.check_content(resumes.load_content(variant)[lang]) == []


CHECKS = {
    "forbidden": [
        {
            "pattern": r"\bXYZ-100\b(?![^.\n·]*(preparaci[oó]n|preparation))",
            "reason": "no aprobada",
        },
        {"pattern": r"\bsenior\b", "reason": "sin experiencia senior"},
    ],
    "required": [{"pattern": r"\bB2\b", "reason": "nivel de inglés"}],
}


def test_checks_flag_forbidden_claims_and_missing_required_ones() -> None:
    content = {"summary": "XYZ-100 certified.", "sections": [{"title": "Senior IT Analyst"}]}

    problems = resumes.check_content(content, CHECKS)

    assert problems == [
        "«XYZ-100»: no aprobada",
        "«Senior»: sin experiencia senior",
        "falta \\bB2\\b: nivel de inglés",
    ]
    assert resumes.check_content({"text": "XYZ-100: en preparación · Inglés B2"}, CHECKS) == []


def test_build_refuses_a_resume_that_breaks_the_checks() -> None:
    path = paths.resumes_dir() / "it-support.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("Nivel 1", "Senior"), encoding="utf-8")

    with pytest.raises(resumes.ResumeCheckFailed, match="Senior"):
        resumes.build(["it-support"], ["es"])  # fails before Playwright is ever imported


def test_count_pages() -> None:
    pdf = b"<< /Type /Pages /Count 2 >> << /Type /Page >> << /Type/Page >>"
    assert resumes.count_pages(pdf) == 2


def test_page_note_warns_only_past_the_limit() -> None:
    assert resumes.page_note(1, max_pages=2) == ""
    assert resumes.page_note(2, max_pages=2) == "2 páginas"
    assert resumes.page_note(3, max_pages=2).startswith("AVISO")
