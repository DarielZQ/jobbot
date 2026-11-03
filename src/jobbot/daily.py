"""Daily scheduled run (ADR-014): HTML report of new matches + Windows toast notification.

The report lands in data/reports/<date>.html and data/reports/latest.html (git-ignored).
"""

from __future__ import annotations

import base64
import html
import sqlite3
import subprocess
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path

from jobbot import paths
from jobbot.config import SearchRules, load_search_rules, load_settings, load_targets
from jobbot.core import db
from jobbot.core.db import JobRow
from jobbot.core.http import HttpClient
from jobbot.core.state import Status
from jobbot.discovery.pipeline import SourceReport, build_sources, run_source
from jobbot.grill import signals
from jobbot.matching.dedupe import applied_twins
from jobbot.matching.language import ResumeAdvice, recommend_resume
from jobbot.matching.rules import RuleSet

# PowerShell's own AppUserModelID: lets a script show toasts without registering an app.
_TOAST_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"


def attention_needed(results: Sequence[tuple[str, SourceReport]]) -> list[tuple[str, str]]:
    """Sources that need the user: not configured (e.g. Gmail token expired) or failing."""
    issues = [(name, r.not_configured) for name, r in results if r.not_configured]
    issues += [(name, r.error) for name, r in results if r.error]
    return issues


def resume_advice(
    conn: sqlite3.Connection, rules: SearchRules, jobs: Sequence[JobRow]
) -> dict[int, ResumeAdvice]:
    """Which CV to send for each job: its role family + the posting's language (ADR-015)."""
    texts = db.descriptions(conn, [j.id for j in jobs])
    return {
        j.id: recommend_resume(rules, j.role_family, j.title, texts.get(j.id, "")) for j in jobs
    }


def _cv_cell(advice: ResumeAdvice | None) -> str:
    if advice is None:
        return ""
    name = html.escape(advice.filename)
    if not advice.path.exists():
        return f'<span title="Genera los PDF con: uv run jobbot resumes">{name}</span>'
    return f'<a href="{html.escape(advice.path.as_uri())}" title="Abrir el PDF">{name}</a>'


def _twin_note(twin: JobRow | None) -> str:
    if twin is None:
        return ""
    return (
        f'<div class="twin">Ya postulaste a una igual: #{twin.id} '
        f"({html.escape(twin.company)})</div>"
    )


def family_labels(rules: SearchRules | None = None) -> dict[str, str]:
    """Report and panel names of the role families, in search.yaml order."""
    rules = rules or load_search_rules()
    return {name: family.label or name for name, family in rules.role_families.items()}


def _family_tables(
    jobs: Sequence[JobRow],
    advice: Mapping[int, ResumeAdvice],
    twins: Mapping[int, JobRow] | None = None,
    labels: Mapping[str, str] | None = None,
) -> list[str]:
    esc = html.escape
    twins = twins or {}
    labels = family_labels() if labels is None else labels
    # Families in config order; jobs of a family since removed from the config, and jobs
    # without one, still show up at the end.
    leftover = sorted({j.role_family or "" for j in jobs} - set(labels), key=lambda f: f == "")
    tables = []
    for family in [*labels, *leftover]:
        group = [j for j in jobs if (j.role_family or "") == family]
        if not group:
            continue
        rows = "\n".join(
            f'<tr><td class="muted">{j.id}</td><td><a href="{esc(j.url)}">{esc(j.title)}</a>'
            f"{_twin_note(twins.get(j.id))}</td>"
            f"<td>{esc(j.company)}</td><td>{esc(j.location)}</td>"
            f'<td class="cv">{_cv_cell(advice.get(j.id))}</td>'
            f'<td class="muted">{esc(j.source)}</td></tr>'
            for j in group
        )
        tables.append(
            f"<h2>{esc(labels.get(family) or family or 'Otras')} ({len(group)})</h2>\n"
            "<table><thead><tr><th>#</th><th>Vacante</th><th>Empresa</th><th>Ubicación</th>"
            f"<th>CV a subir</th><th>Fuente</th></tr></thead><tbody>\n{rows}\n</tbody></table>"
        )
    return tables


def render_report(
    new_jobs: Sequence[JobRow],
    results: Sequence[tuple[str, SourceReport]],
    pending: Sequence[JobRow],
    advice: Mapping[int, ResumeAdvice],
    generated_at: datetime,
    applied_total: int = 0,
    twins: Mapping[int, JobRow] | None = None,
    labels: Mapping[str, str] | None = None,
    decisions: int = 0,
) -> str:
    """`pending`: every open job (new ones included). Empty `results` = regenerated offline.
    `twins`: open jobs that look like one already applied to (applied_twins).
    `decisions`: grill-me questions waiting for an answer."""
    esc = html.escape
    labels = family_labels() if labels is None else labels
    body = "\n".join(_family_tables(new_jobs, advice, twins, labels))
    body = body or '<p class="empty">No hay vacantes nuevas que encajen.</p>'

    new_ids = {j.id for j in new_jobs}
    older = [j for j in pending if j.id not in new_ids]
    if older:
        opened = "" if new_jobs else " open"
        body += (
            f"\n<details{opened}><summary>Pendientes de postular de días anteriores "
            f"({len(older)})</summary>\n"
            + "\n".join(_family_tables(older, advice, twins, labels))
            + "\n</details>"
        )

    issues = attention_needed(results)
    warnings = ""
    if issues:
        items = "\n".join(f"<li><b>{esc(n)}</b>: {esc(msg)}</li>" for n, msg in issues)
        warnings = f'<div class="warn"><h2>Necesita tu atención</h2><ul>{items}</ul></div>'
    if decisions:
        noun = "decisión pendiente" if decisions == 1 else "decisiones pendientes"
        warnings += (
            f'<div class="warn"><p>Tienes {decisions} {noun}: respóndelas en la pestaña '
            "Decisiones del panel o con <code>jobbot grill pendientes</code>.</p></div>"
        )

    if results:
        checked = sum(1 for _, r in results if not (r.skipped_recent or r.not_configured))
        checked_text = f"{checked} fuentes revisadas"
    else:
        checked_text = "regenerado sin consultar fuentes (nuevas = últimas 24 h)"
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>JobBot · {generated_at:%Y-%m-%d}</title>
<style>
  :root {{ --bg:#f7f8fa; --fg:#1d232b; --muted:#5b6573; --card:#fff; --line:#dde3ea;
          --accent:#1f4e79; --warn-bg:#fff4e5; --warn-line:#f0b45a; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#14181d; --fg:#e6e9ee; --muted:#9aa4b1; --card:#1c2128; --line:#2c333c;
            --accent:#7fb3e6; --warn-bg:#2b2316; --warn-line:#8a6420; }}
  }}
  body {{ margin:0; padding:24px 16px; background:var(--bg); color:var(--fg);
         font:15px/1.45 "Segoe UI", system-ui, sans-serif; }}
  main {{ max-width:1080px; margin:0 auto; }}
  h1 {{ margin:0 0 4px; color:var(--accent); font-size:24px; }}
  h2 {{ font-size:17px; margin:24px 0 8px; }}
  .muted, .meta {{ color:var(--muted); }}
  table {{ width:100%; border-collapse:collapse; background:var(--card);
          border:1px solid var(--line); }}
  th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--line);
           vertical-align:top; }}
  th {{ font-size:13px; color:var(--muted); font-weight:600; }}
  td.cv {{ white-space:nowrap; font-size:13px; }}
  a {{ color:var(--accent); }}
  details {{ margin-top:28px; }}
  summary {{ cursor:pointer; font-weight:600; font-size:17px; }}
  .warn {{ background:var(--warn-bg); border:1px solid var(--warn-line);
          padding:4px 16px; margin-top:16px; }}
  .empty {{ background:var(--card); border:1px solid var(--line); padding:16px; }}
  .twin {{ display:inline-block; margin-top:4px; padding:1px 8px; font-size:13px;
          background:var(--warn-bg); border:1px solid var(--warn-line); }}
  @media (max-width:640px) {{
    th:nth-child(1), td:nth-child(1), th:nth-child(6), td:nth-child(6) {{ display:none; }}
  }}
</style>
</head>
<body><main>
<h1>Vacantes nuevas: {len(new_jobs)}</h1>
<p class="meta">{generated_at:%d/%m/%Y %H:%M} · {checked_text} ·
{len(pending)} pendientes de postular · {applied_total} postuladas</p>
{warnings}
{body}
<p class="meta">CV a subir: el de la familia del puesto, en el idioma del anuncio; clic para abrir
el PDF. Para marcar a cuáles postulaste, abre el panel con el acceso directo
<b>JobBot</b> del escritorio (o <code>jobbot panel</code>). Generado por JobBot.</p>
</main></body></html>
"""


def write_report(
    conn: sqlite3.Connection,
    rules: SearchRules,
    new_jobs: Sequence[JobRow],
    results: Sequence[tuple[str, SourceReport]],
    reports_dir: Path,
    now: datetime | None = None,
) -> Path:
    """latest.html, plus a dated copy when it comes from a real run (`results` not empty)."""
    now = now or datetime.now()
    pending = db.list_jobs(conn, status=Status.DISCOVERED, limit=100_000)
    applied = db.list_jobs(conn, status=Status.SUBMITTED, limit=100_000)
    content = render_report(
        new_jobs,
        results,
        pending,
        resume_advice(conn, rules, pending),
        now,
        len(applied),
        applied_twins(pending, db.applied_jobs(conn)),
        family_labels(rules),
        len(signals.pending(conn)),
    )
    reports_dir.mkdir(parents=True, exist_ok=True)
    if results:
        (reports_dir / f"{now:%Y-%m-%d}.html").write_text(content, encoding="utf-8")
    latest = reports_dir / "latest.html"
    latest.write_text(content, encoding="utf-8")
    return latest


def run_all(
    conn: sqlite3.Connection,
    client: HttpClient,
    on_result: Callable[[str, SourceReport, int, int], None] | None = None,
) -> tuple[list[JobRow], list[tuple[str, SourceReport]], Path]:
    """Every source of config/targets.yaml, then the report. `on_result(name, report, done, total)`
    reports progress (CLI output, panel progress bar)."""
    rules = load_search_rules()
    ruleset = RuleSet(rules)
    started = db.utc_now()
    disabled = set(load_settings().disabled_sources)
    sources = [s for s in build_sources(load_targets(), client) if s.name not in disabled]
    results: list[tuple[str, SourceReport]] = []
    for source in sources:
        report = run_source(source, conn, ruleset)
        results.append((source.name, report))
        if on_result:
            on_result(source.name, report, len(results), len(sources))
    signals.record_runs(conn, results)
    signals.refresh(conn)  # grill-me questions from what this run saw
    new_jobs = db.new_matches_since(conn, started)
    return new_jobs, results, write_report(conn, rules, new_jobs, results, paths.reports_dir())


def notification(
    new_jobs: Sequence[JobRow],
    results: Sequence[tuple[str, SourceReport]],
    labels: Mapping[str, str] | None = None,
) -> tuple[str, str] | None:
    """(title, body) for the toast, or None when there is nothing worth interrupting for."""
    issues = attention_needed(results)
    if not new_jobs and not issues:
        return None
    if new_jobs:
        labels = family_labels() if labels is None else labels
        counts = [
            f"{sum(1 for j in new_jobs if j.role_family == fam)} de {label}"
            for fam, label in labels.items()
            if any(j.role_family == fam for j in new_jobs)
        ]
        noun = "vacante nueva" if len(new_jobs) == 1 else "vacantes nuevas"
        title = f"JobBot: {len(new_jobs)} {noun}"
        title += f" ({', '.join(counts)})" if counts else ""
        lines = [f"{j.title} · {j.company}" for j in new_jobs[:3]]
        if len(new_jobs) > 3:
            lines.append(f"y {len(new_jobs) - 3} más")
    else:
        title = "JobBot: hoy no hay vacantes nuevas"
        lines = []
    if issues:
        lines.append(f"Atención: {issues[0][0]} ({issues[0][1][:60]})")
    return title, "\n".join(lines)


def notify_windows(title: str, body: str, launch: Path | None = None) -> bool:
    """Show a Windows toast; clicking it opens `launch`. Returns False if it could not be shown."""
    esc = html.escape
    launch_attr = f' activationType="protocol" launch="{esc(launch.as_uri())}"' if launch else ""
    toast_xml = (
        f'<toast{launch_attr}><visual><binding template="ToastGeneric">'
        f"<text>{esc(title)}</text><text>{esc(body)}</text>"
        "</binding></visual></toast>"
    )
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
        "ContentType = WindowsRuntime] > $null\n"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, "
        "ContentType = WindowsRuntime] > $null\n"
        "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument\n"
        f"$xml.LoadXml('{toast_xml.replace(chr(39), chr(39) * 2)}')\n"
        "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)\n"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
        f"'{_TOAST_APP_ID}').Show($toast)\n"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0
