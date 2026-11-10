from __future__ import annotations

import pytest

from conftest import make_job
from jobbot.config import load_search_rules
from jobbot.matching.rules import RuleSet

# The example the preset leaves commented out for people who only work inside the GAM.
OUTSIDE_GAM = (
    r"\b(guanacaste|liberia|limon|puntarenas|perez zeledon|san carlos|nicoya"
    r"|golfito)\b"
)


@pytest.fixture
def rules_gam_only() -> RuleSet:
    search = load_search_rules()
    search.location.local_exclude = [OUTSIDE_GAM]
    return RuleSet(search)


@pytest.mark.parametrize(
    "title",
    [
        "IT Support Analyst - Level 1",
        "Help Desk Technician",
        "Service Desk Analyst (Bilingual)",
        "Technical Support Representative",
        "Desktop Support Technician",
        "Cloud Support Associate",
        "Junior Cloud Engineer",
        "Applications Support Analyst",
        "Network Support Engineer",
        "Técnico de Soporte",
        "Analista de Soporte TI",
        "Agente de Mesa de Ayuda",
        "IT Help Desk Associate (Level 1/2)",
        "Técnico de soporte N1/N2",
        # Nivel 2: el candidato decidió intentarlo (2026-11-01)
        "IT Support Analyst II",
        "Support Engineer II - Ext, Partner Tech Engineering",
        "Technical Support Expert (Tier 2), Americas/BRT",
        "Technical Support Engineer L2",
        "Tecnico TI Mesa de ayuda n2",
        "Mid Support Engineer",
        # Empresas remotas (ADR-021): TI interna y el soporte de Automattic
        "IT Engineer | LATAM",
        "Happiness Engineer",
        "Technical Support Engineer Intern",
        "IT Intern",
        "IT Infrastructure Internship",
        "Cloud Trainee",
        "Pasantía en Soporte TI",
        "Practicante de Tecnología",
        "Intern - IT",
        "Early Career Program - IT Operations",
        "New Grad - IT Support",
        "Data Center Technician",
        "Junior Networking Agent - Audio Products (Entry Level)",
        "Incident Management Engineer, Incident Detection and Response",
        "Auxiliar de tecnología",
        "Profesional en Tecnologías de Información",
        # Puestos cercanos al perfil
        "Field Service Technician",
        "Smart Hands Technician",
        "End User Computing Technician",
        "Workplace Technology Analyst",
        "IMAC Technician",
        "Storage Hardware Operations Intern",
        "Técnico en Informática",
        "Técnico en Redes",
        "Técnico en mantenimiento de equipo de cómputo",
        "IT Asset Analyst",
        "Hardware Asset Management Specialist",
        "Técnico de Inventario TI",
        "ITSM Analyst",
        "ServiceNow Administrator",
        "Service Request Analyst",
        "Problem Management Analyst",
        "Identity and Access Management Analyst",
        "Access Management Specialist",
        "User Provisioning Analyst",
        "Analista de Accesos e Identidades",
        "IT Operations Analyst",
        "Infrastructure Monitoring Technician",
        "Command Center Analyst",
        "NOC Operator",
        "Operador de monitoreo",
        "Junior System Administrator",
        "Windows Administrator",
        "Administrador de sistemas",
        "Administrador de infraestructura",
        "Endpoint Management Analyst",
        "Intune Engineer",
        "Microsoft 365 Administrator",
        "Network Technician",
        "Junior Network Engineer",
        "Analista de Redes",
    ],
)
def test_it_support_titles_pass(rules: RuleSet, title: str) -> None:
    result = rules.evaluate(make_job(title=title))
    assert (result.ok, result.role_family) == (True, "it_support")


@pytest.mark.parametrize(
    "title",
    [
        "Data Analyst",
        "Junior Data Analyst",
        "Reporting Analyst",
        "Business Intelligence Analyst I",
        "Data Management Analyst",
        "Master Data Analyst",
        "Analista de Datos",
        "ETL Developer",
        "Data Operations Analyst",
        "Data Operations Analyst- Intermediate",
        "RPA Developer",
        "AI Data Trainer",
        "Data Annotation Specialist",
        "Junior Data Scientist",
        "Data Engineer I",
        "Associate Machine Learning Engineer",
        "Data Analytics Intern",
        "Pasantía en Análisis de Datos",
        "Database Administrator",
        "Junior DBA",
        "Administrador de Bases de Datos",
    ],
)
def test_data_ai_titles_pass(rules: RuleSet, title: str) -> None:
    result = rules.evaluate(make_job(title=title))
    assert (result.ok, result.role_family) == (True, "data_ai")


@pytest.mark.parametrize(
    "title",
    [
        "Data Scientist",  # sin marca de nivel de entrada
        "Machine Learning Engineer",
        "Data Entry Clerk",
        "Data Privacy Analyst",
        "Senior Data Analyst",
    ],
)
def test_data_ai_titles_rejected(rules: RuleSet, title: str) -> None:
    assert not rules.evaluate(make_job(title=title)).ok


def test_place_outside_gam_in_title_is_rejected(rules_gam_only: RuleSet) -> None:
    job = make_job(
        title="Técnico de soporte regional data center N1 (San Carlos)", location="San José"
    )
    assert rules_gam_only.evaluate(job).reason == "location_outside_area: san carlos"


def test_preset_accepts_the_whole_country_unless_told_otherwise(rules: RuleSet) -> None:
    assert rules.evaluate(make_job(location="Liberia, Guanacaste, Costa Rica")).ok


def test_it_support_family_wins_over_data_family(rules: RuleSet) -> None:
    # Matches both families: the primary one is reported.
    assert rules.classify("IT Support Data Analyst") == "it_support"


@pytest.mark.parametrize(
    ("title", "reason_prefix"),
    [
        ("Senior IT Support Analyst", "title_excluded"),
        ("Senior IT Engineer", "title_excluded"),
        ("Sr. Service Desk Analyst", "title_excluded"),
        ("Help Desk Manager", "title_excluded"),
        ("Gerente de Soporte", "title_excluded"),
        ("IT Support Engineer L3", "title_excluded"),
        ("Service Desk Analyst III", "title_excluded"),
        ("Técnico de Soporte Nivel 3", "title_excluded"),
        ("Supply Chain Planning Intern", "title_not_target_role"),
        ("Intern - Bachelors Tech", "title_not_target_role"),
        ("Technical Writing Intern", "title_not_target_role"),
        ("Finance Trainee", "title_not_target_role"),
        ("Customer Service Representative", "title_not_target_role"),
        ("Accounts Payable Analyst", "title_not_target_role"),
        ("Machine Operator I.", "title_not_target_role"),
        ("Major Incident Response Mgr, SP-Support Command Center", "title_excluded"),
        # Fuera del plan del candidato por ahora: SOC y QA
        ("SOC Analyst I", "title_not_target_role"),
        ("Security Operations Center Analyst", "title_not_target_role"),
        ("Analista QA Junior", "title_not_target_role"),
        # Mismo vocabulario, otra área
        ("Analista de Redes Sociales", "title_not_target_role"),
        ("Transportation Network Analyst", "title_not_target_role"),
        ("Market Access Analyst", "title_not_target_role"),
        ("Transaction Monitoring Analyst", "title_not_target_role"),
        ("Analista Monitoreo Transaccional", "title_not_target_role"),
        ("Operador de monitoreo de cámaras", "title_not_target_role"),
        ("Técnico de Control de Accesos", "title_not_target_role"),
        ("Asset Management Analyst", "title_not_target_role"),
        ("Batch Release Specialist", "title_not_target_role"),
        ("Configuration Management Specialist", "title_not_target_role"),
        ("Salesforce Administrator", "title_not_target_role"),
        ("Contract Administrator (Internship)", "title_not_target_role"),
        ("Laboratory Technician", "title_not_target_role"),
        # Idiomas que el candidato no habla
        ("(fluent English & French) Customer Support Consultant", "title_excluded"),
        ("Technical Support - ECAD Software (m/w/d)", "title_excluded"),
        ("Soporte técnico con portugués", "title_excluded"),
    ],
)
def test_non_target_titles_rejected(rules: RuleSet, title: str, reason_prefix: str) -> None:
    result = rules.evaluate(make_job(title=title))
    assert not result.ok
    assert result.reason.startswith(reason_prefix)


@pytest.mark.parametrize(
    "location",
    [
        "Heredia, Costa Rica",
        "CRI - Heredia",
        "Lagunilla, Costa Rica",
        "San José",
        "Escazú, San José",
        "Remote - LATAM",
    ],
)
def test_locations_accepted(rules: RuleSet, location: str) -> None:
    assert rules.evaluate(make_job(location=location)).ok


@pytest.mark.parametrize(
    ("location", "remote", "reason"),
    [
        ("Austin, TX", False, "location_not_target"),
        ("Liberia, Guanacaste, Costa Rica", False, "location_outside_area: liberia"),
        ("Remote - US only", True, "remote_not_eligible: us only"),
        ("Remote", True, "remote_region_unknown"),
    ],
)
def test_locations_rejected(
    rules_gam_only: RuleSet, location: str, remote: bool, reason: str
) -> None:
    result = rules_gam_only.evaluate(make_job(location=location, remote=remote))
    assert (result.ok, result.reason) == (False, reason)


@pytest.mark.parametrize(
    "description",
    [
        "Active security clearance required.",
        "Must be a US citizen.",
        "Seniority: Senior.\nGreat team.",
    ],
)
def test_descriptions_with_hard_blockers_rejected(rules: RuleSet, description: str) -> None:
    result = rules.evaluate(make_job(description=description))
    assert not result.ok
    assert result.reason.startswith("description_excluded")


@pytest.mark.parametrize(
    "description",
    [
        # Years asked are not filtered: companies often inflate them (decision of 2026-11-01).
        "Requires 3+ years of experience in IT support.",
        "Mínimo de 3 años de experiencia en soporte.",
        "3-5 years of experience in technical support.",
        "1-3 years of experience in IT support.",
        "<p>0&ndash;2 years experience</p>",
        "Seniority: Semi Senior.",
        "",
    ],
)
def test_descriptions_asking_for_years_pass(rules: RuleSet, description: str) -> None:
    assert rules.evaluate(make_job(description=description)).ok
