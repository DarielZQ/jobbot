"""Command line entry point: `uv run jobbot <command>`."""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jobbot import initialize, paths
from jobbot.config import (
    EmailAlertsTarget,
    Settings,
    load_search_rules,
    load_settings,
    load_targets,
    resolve,
)
from jobbot.core import db
from jobbot.core.http import HttpClient
from jobbot.core.state import InvalidTransition, Status
from jobbot.discovery.applications import NAME as CONFIRMATIONS
from jobbot.discovery.base import SourceNotConfigured
from jobbot.discovery.pipeline import SourceReport, build_sources, rescreen, run_source
from jobbot.matching.dedupe import applied_twins
from jobbot.matching.rules import RuleSet


def load_dotenv() -> None:
    """Minimal loader of <data folder>/.env (KEY=VALUE lines); real environment variables win.

    JOBBOT_HOME itself can only come from the real environment: it says where .env is.
    """
    path = paths.home() / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _http_client(settings: Settings) -> HttpClient:
    http = settings.http
    return HttpClient(
        timeout_s=http.timeout_s,
        min_interval_s=http.min_interval_s,
        max_retries=http.max_retries,
        host_min_interval_s=http.host_min_interval_s,
    )


def report_line(name: str, report: SourceReport) -> str:
    if report.skipped_recent:
        return f"{name:<28} omitida: consultada hace poco ({report.skipped_recent})"
    if report.not_configured:
        return f"{name:<28} sin configurar: {report.not_configured}"
    if report.confirmations is not None or (report.error and name == CONFIRMATIONS):
        line = (
            f"{name:<28} confirmaciones: {report.confirmations or 0:>3}  "
            f"marcadas como postuladas: {report.marked_applied:>3}"
        )
        return f"{line}  ERROR {report.error}" if report.error else line
    line = (
        f"{name:<28} nuevas OK: {report.new_matched:>3}  "
        f"descartadas: {report.new_skipped:>4}  ya vistas: {report.seen:>4}"
    )
    if report.skip_reasons:
        top = ", ".join(f"{k}={v}" for k, v in report.skip_reasons.most_common(3))
        line += f"  [{top}]"
    if report.screened_out:
        line += f"  descartadas al ver su descripción: {report.screened_out}"
    if report.error:
        line += f"  ERROR {report.error}"
    return line


def cmd_daily(_: argparse.Namespace) -> int:
    """Scheduled run: discover everywhere, write the HTML report, notify if there is news."""
    from jobbot import daily

    settings = load_settings()
    conn = db.connect(settings.db_path())
    with _http_client(settings) as client:
        new_jobs, results, path = daily.run_all(
            conn, client, lambda name, report, *_: print(report_line(name, report))
        )
    open_total = len(db.list_jobs(conn, status=Status.DISCOVERED, limit=100_000))
    print(f"\nVacantes nuevas que encajan: {len(new_jobs)} (pendientes en total: {open_total})")
    print(f"Informe: {path}")
    if settings.notifications.windows_toast and sys.platform == "win32":
        message = daily.notification(new_jobs, results)
        if message and not daily.notify_windows(*message, launch=path):
            print("No se pudo mostrar la notificación de Windows.")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Rebuild latest.html from the database only (e.g. after `jobbot applied`)."""
    from jobbot import daily

    conn = db.connect(load_settings().db_path())
    since = (datetime.now(UTC) - timedelta(hours=24)).isoformat(timespec="seconds")
    path = daily.write_report(
        conn, load_search_rules(), db.new_matches_since(conn, since), [], paths.reports_dir()
    )
    print(f"Informe actualizado: {path}")
    if args.open:
        webbrowser.open(path.as_uri())
    return 0


YES = {"s", "si", "sí", "y", "yes"}


def cmd_grill(args: argparse.Namespace) -> int:
    """grill-me: an interview by topic, or the decisions the daily run queued."""
    from jobbot import grill
    from jobbot.grill import apply, signals

    if args.topic == "pendientes":
        conn = db.connect(load_settings().db_path())
        decisions = signals.pending(conn)
        if not decisions:
            print("No hay decisiones pendientes.")
            return 0
        for number, decision in enumerate(decisions, 1):
            question = grill.Question(
                decision.key, decision.question, decision.options,
                recommended=decision.recommended, reason=decision.reason,
            )  # fmt: skip
            print("\n" + grill.render(question, number))
            while (choice := grill.parse(question, input(f"Q{number}: "))) is None:
                print("   Elige una letra de las opciones.")
            print("   " + signals.answer(conn, decision.id, choice))
        return 0

    topic = grill.load_topic(args.topic)
    answers = grill.interview(topic)
    changes = apply.plan(answers, topic.questions)
    if not changes.changes:
        print("\nNada que cambiar.")
        return 0
    print("\nEstos son los cambios que voy a guardar:")
    for change in changes.changes:
        print(f"  - {change}")
    if input("\n¿Los guardo? [s/N] ").strip().lower() not in YES:
        print("No se guardó nada.")
        return 1
    for path in changes.save():
        print(f"Guardado: {paths.shown(path)}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    """Create the data folder from the templates; never overwrites the user's files."""
    created = initialize.init_home(args.preset)
    home = paths.home()
    print(f"Carpeta de datos: {home}")
    for path in created:
        print(f"  creado: {paths.shown(path)}")
    if not created:
        print("  Ya estaba lista: no se cambió nada.")
    print(
        "\nSiguiente paso: uv run jobbot grill setup-profile (o edita profile/ y config/ a mano)."
        "\nEl perfil de ejemplo es ficticio: reemplázalo antes de postular."
    )
    return 0


def cmd_panel(args: argparse.Namespace) -> int:
    """Local web panel (ADR-016): the job list with buttons instead of commands."""
    from jobbot import panel

    settings = load_settings()
    db_path = Path(args.db) if args.db else settings.db_path()
    return panel.serve(
        db_path,
        lambda: _http_client(settings),
        port=args.port or settings.panel.port,
        open_browser=not args.no_browser,
    )


def panel_main() -> int:
    """Entry point of `jobbot-panel.exe` (no console window): the desktop shortcut."""
    return main(["panel"])


def cmd_applied(args: argparse.Namespace) -> int:
    """Mark jobs the candidate applied to by hand, so they leave the pending list."""
    conn = db.connect(load_settings().db_path())
    failed = 0
    for job_id in args.ids:
        try:
            job = db.mark_applied(conn, job_id, undo=args.undo)
        except KeyError:
            print(f"#{job_id}: no existe.")
            failed += 1
            continue
        except InvalidTransition:
            current = db.get_job(conn, job_id)
            state = current.status.value if current else "?"
            hint = " (solo se deshace una marca manual o por correo)" if args.undo else ""
            print(f"#{job_id}: no se puede, está en estado {state}{hint}.")
            failed += 1
            continue
        verb = "Vuelve a pendientes" if args.undo else "Postulada"
        print(f"{verb}: #{job.id} {job.title} · {job.company}")
    if failed < len(args.ids):
        print("Actualiza el informe con: uv run jobbot report")
    return 1 if failed else 0


def cmd_discover(args: argparse.Namespace) -> int:
    settings = load_settings()
    rules = RuleSet(load_search_rules())
    conn = db.connect(settings.db_path())
    with _http_client(settings) as client:
        sources = [
            s
            for s in build_sources(load_targets(), client)
            if (not args.source or args.source in s.name)
            and s.name not in settings.disabled_sources
        ]
        if not sources:
            print("No hay fuentes que coincidan en config/targets.yaml.")
            return 1
        failed = 0
        for source in sources:
            report = run_source(source, conn, rules)
            failed += bool(report.error)
            print(report_line(source.name, report))
    return 1 if failed == len(sources) else 0


def _gmail_paths() -> tuple[EmailAlertsTarget, Path, Path]:
    alerts = load_targets().email_alerts or EmailAlertsTarget()
    return alerts, resolve(alerts.credentials_file), resolve(alerts.token_file)


def cmd_gmail_login(_: argparse.Namespace) -> int:
    from jobbot.mail import gmail

    _, credentials, token = _gmail_paths()
    try:
        gmail.login(credentials, token)
        with _http_client(load_settings()) as client:
            mail = gmail.GmailClient(client, lambda: gmail.access_token(credentials, token))
            email = mail.profile_email()
    except SourceNotConfigured as exc:
        print(f"No se pudo autorizar Gmail: {exc}")
        return 1
    print(f"Gmail autorizado en modo solo lectura para {email}.")
    print(f"Token guardado en {paths.shown(token)} (tu carpeta de datos, fuera de cualquier repo).")
    return 0


def cmd_alerts_sample(args: argparse.Namespace) -> int:
    """Save the latest alert emails to data/email_samples/ and show what the parser extracts."""
    from jobbot.discovery.email_alerts import PARSERS
    from jobbot.mail import gmail

    alerts, credentials, token = _gmail_paths()
    feed = getattr(alerts, args.feed)
    if feed is None:
        print(f"No hay `email_alerts.{args.feed}` en config/targets.yaml.")
        return 1
    out_dir = paths.data_dir() / "email_samples"
    out_dir.mkdir(parents=True, exist_ok=True)
    query = f"({feed.query}) newer_than:{alerts.lookback_days}d"
    try:
        with _http_client(load_settings()) as client:
            mail = gmail.GmailClient(client, lambda: gmail.access_token(credentials, token))
            ids = mail.search(query, args.limit)
            if not ids:
                print(f"No hay correos que coincidan con: {query}")
                return 0
            for message_id in ids:
                message = mail.get(message_id)
                base = out_dir / f"{args.feed}_{message_id}"
                base.with_suffix(".txt").write_text(message.text, encoding="utf-8")
                base.with_suffix(".html").write_text(message.html, encoding="utf-8")
                jobs = PARSERS[args.feed](message, f"email:{args.feed}", feed.default_location)
                print(f"\n{message.subject}")
                print(f"  Guardado: {paths.shown(base)}.txt/.html")
                print(f"  Vacantes reconocidas: {len(jobs)}")
                for job in jobs[:10]:
                    print(f"    - {job.title} | {job.company} | {job.location}")
    except SourceNotConfigured as exc:
        print(f"Gmail sin configurar: {exc}")
        return 1
    print("\nLas muestras contienen el texto de esos correos; bórralas cuando ya no sirvan.")
    return 0


def cmd_alerts_status(_: argparse.Namespace) -> int:
    """Per feed: how many alert emails arrived and the latest one (headers only, no bodies)."""
    from jobbot.discovery.email_alerts import PARSERS
    from jobbot.mail import gmail

    alerts, credentials, token = _gmail_paths()
    try:
        with _http_client(load_settings()) as client:
            mail = gmail.GmailClient(client, lambda: gmail.access_token(credentials, token))
            print(f"Correos de los últimos {alerts.lookback_days} días:")
            for feed_name in PARSERS:
                feed = getattr(alerts, feed_name)
                if feed is None:
                    print(f"  {feed_name:<13} sin configurar en config/targets.yaml")
                    continue
                query = f"({feed.query}) newer_than:{alerts.lookback_days}d"
                ids = mail.search(query, alerts.max_messages)
                if not ids:
                    print(f"  {feed_name:<13} 0 correos  <- revisa la alerta en el sitio")
                    continue
                latest = mail.headers(ids[0])
                print(
                    f"  {feed_name:<13} {len(ids):>2} correos  último: "
                    f"{latest.get('Date', '')[:16]} | {latest.get('Subject', '')[:60]}"
                )
    except SourceNotConfigured as exc:
        print(f"Gmail sin configurar: {exc}")
        return 1
    return 0


def cmd_rescreen(_: argparse.Namespace) -> int:
    conn = db.connect(load_settings().db_path())
    changes = rescreen(conn, RuleSet(load_search_rules()))
    print(
        f"Reabiertas (ahora pasan los filtros): {changes['reopened']}\n"
        f"Ahora descartadas: {changes['newly_skipped']}\n"
        f"Motivo de descarte actualizado: {changes['reason_updated']}"
    )
    return 0


def cmd_jobs(args: argparse.Namespace) -> int:
    from jobbot.daily import resume_advice

    conn = db.connect(load_settings().db_path())
    status = None if args.all else Status(args.status)
    rows = db.list_jobs(conn, status=status, role_family=args.family, limit=args.limit)
    if not rows:
        print("Sin resultados.")
        return 0
    open_rows = [r for r in rows if r.status == Status.DISCOVERED]
    advice = resume_advice(conn, load_search_rules(), open_rows)
    twins = applied_twins(open_rows, db.applied_jobs(conn))
    for row in rows:
        family = f"[{row.role_family}]" if row.role_family else ""
        print(
            f"#{row.id:<5} {family:<13} {row.company[:18]:<18} {row.title[:50]:<50} "
            f"{row.location[:28]}"
        )
        print(f"       {row.url}")
        if row.id in advice:
            print(f"       CV: {advice[row.id].filename}")
        if twin := twins.get(row.id):
            print(f"       Ojo: parece la misma que #{twin.id} ({twin.company}), ya postulada")
        if row.status_reason:
            print(f"       {row.status.value}: {row.status_reason}")
    return 0


def cmd_stats(_: argparse.Namespace) -> int:
    conn = db.connect(load_settings().db_path())
    rows = db.stats(conn)
    if not rows:
        print("Base de datos vacía. Corre `jobbot discover` primero.")
        return 0
    for source, family, status, count in rows:
        print(f"{source:<28} {family or '-':<12} {status:<18} {count:>5}")
    return 0


def cmd_resumes(args: argparse.Namespace) -> int:
    from jobbot import resumes

    selected = [args.variant] if args.variant else resumes.variants()
    langs = [args.lang] if args.lang else list(resumes.LANGS)
    if not selected:
        print("No hay contenido de CV en profile/resumes/*.yaml.")
        return 1
    max_pages = load_settings().resumes.max_pages
    warnings = 0
    try:
        built = resumes.build(selected, langs)
    except resumes.ResumeCheckFailed as exc:
        print("No se generó ningún PDF: estos CV rompen profile/resumes/checks.yaml:")
        print(str(exc))
        return 1
    except ImportError:
        print("Falta el extra de CV en PDF. Instálalo con:")
        print("  uv sync --extra resumes")
        print("  uv run playwright install chromium")
        return 1
    for item in built:
        note = resumes.page_note(item.pages, max_pages)
        warnings += item.pages > max_pages
        print(f"{paths.shown(item.path)}{'  ' + note if note else ''}")
    return 1 if warnings else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobbot", description="JobBot: búsqueda de empleo local")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser(
        "init", help="Crear tu carpeta de datos (JOBBOT_HOME, por defecto ~/JobBot) con un preset"
    )
    init.add_argument("--preset", choices=initialize.presets(), default="costa-rica-it")
    init.set_defaults(func=cmd_init)

    from jobbot.grill import topics

    grill_cmd = sub.add_parser(
        "grill", help="Preguntas para configurar tu búsqueda o decidir pendientes (grill-me)"
    )
    grill_cmd.add_argument("topic", choices=[*topics(), "pendientes"])
    grill_cmd.set_defaults(func=cmd_grill)

    discover = sub.add_parser("discover", help="Descubrir vacantes en config/targets.yaml")
    discover.add_argument("--source", help="Solo fuentes cuyo nombre contenga este texto")
    discover.set_defaults(func=cmd_discover)

    daily_cmd = sub.add_parser(
        "daily", help="Corrida programada: buscar, generar informe y notificar si hay novedades"
    )
    daily_cmd.set_defaults(func=cmd_daily)

    report = sub.add_parser(
        "report", help="Regenerar data/reports/latest.html sin consultar fuentes"
    )
    report.add_argument("--open", action="store_true", help="Abrirlo en el navegador")
    report.set_defaults(func=cmd_report)

    panel_cmd = sub.add_parser("panel", help="Abrir el panel de vacantes en el navegador")
    panel_cmd.add_argument("--port", type=int, help="Puerto local (por defecto: settings.yaml)")
    panel_cmd.add_argument("--db", help="Otra base de datos (p. ej. una copia para pruebas)")
    panel_cmd.add_argument("--no-browser", action="store_true", help="No abrir el navegador")
    panel_cmd.set_defaults(func=cmd_panel)

    applied = sub.add_parser("applied", help="Marcar vacantes a las que ya postulaste (por su #)")
    applied.add_argument("ids", type=int, nargs="+", metavar="ID")
    applied.add_argument("--undo", action="store_true", help="Deshacer la marca")
    applied.set_defaults(func=cmd_applied)

    jobs = sub.add_parser("jobs", help="Listar vacantes")
    jobs.add_argument(
        "--status", default=Status.DISCOVERED.value, choices=[s.value for s in Status]
    )
    jobs.add_argument("--all", action="store_true", help="Todos los estados")
    jobs.add_argument(
        "--family", help="Solo una familia de roles de config/search.yaml (p. ej. data_ai)"
    )
    jobs.add_argument("--limit", type=int, default=50)
    jobs.set_defaults(func=cmd_jobs)

    status = sub.add_parser(
        "alerts-status", help="Cuántas alertas por correo llegaron por sitio (solo encabezados)"
    )
    status.set_defaults(func=cmd_alerts_status)

    login = sub.add_parser("gmail-login", help="Autorizar lectura de Gmail (solo lectura)")
    login.set_defaults(func=cmd_gmail_login)

    sample = sub.add_parser(
        "alerts-sample", help="Guardar correos de alerta recientes y probar el lector"
    )
    sample.add_argument(
        "--feed", choices=["linkedin", "computrabajo", "indeed", "elempleo"], default="linkedin"
    )
    sample.add_argument("--limit", type=int, default=1)
    sample.set_defaults(func=cmd_alerts_sample)

    rescreen_cmd = sub.add_parser(
        "rescreen", help="Reaplicar config/search.yaml a las vacantes guardadas (sin red)"
    )
    rescreen_cmd.set_defaults(func=cmd_rescreen)

    stats = sub.add_parser("stats", help="Conteo por fuente y estado")
    stats.set_defaults(func=cmd_stats)

    resumes_cmd = sub.add_parser("resumes", help="Generar los PDF de CV desde profile/resumes/")
    resumes_cmd.add_argument("--variant", help="p. ej. it-support o data-ai")
    resumes_cmd.add_argument("--lang", choices=["es", "en"])
    resumes_cmd.set_defaults(func=cmd_resumes)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    if args.func is not cmd_init and not initialize.is_initialized():
        print(f"No encuentro tu configuración en {paths.home()}.")
        print("Créala con:  uv run jobbot init --preset costa-rica-it   (o --preset remote-latam)")
        print("¿Tus datos están en otra carpeta? Indícala con la variable JOBBOT_HOME.")
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
