"""Local web panel (ADR-016): the job list with buttons instead of CLI commands.

Listens on 127.0.0.1 only. Every request must carry the panel's own Host (DNS rebinding);
writes must be JSON POSTs from the panel's own Origin, so another web page open in the same
browser cannot trigger them (no CORS headers are ever sent). It stops by itself once the page
has been closed for a while, so the desktop shortcut can run it without a console window.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import sys
import threading
import time
import urllib.request
import webbrowser
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from jobbot import daily, paths
from jobbot.config import load_search_rules
from jobbot.core import db
from jobbot.core.db import JobRow
from jobbot.core.http import HttpClient
from jobbot.core.state import InvalidTransition, Status
from jobbot.grill import signals
from jobbot.matching.dedupe import applied_twins
from jobbot.matching.language import ResumeAdvice
from jobbot.matching.rules import RuleSet

log = logging.getLogger("jobbot.panel")

STATIC_DIR = Path(__file__).parent
IDLE_SHUTDOWN_S = 10 * 60  # the page polls every minute while open
_CV_NAME = re.compile(r"^[a-z0-9-]+_(es|en)\.pdf$")
_JOB_ACTION = re.compile(r"^/api/jobs/(\d+)/([a-z_]+)$")
_DECISION = re.compile(r"^/api/decisions/(\d+)$")

VIEWS: dict[str, tuple[Status, ...]] = {
    "pending": (Status.DISCOVERED,),
    "applied": (Status.SUBMITTED, Status.CONFIRMED, Status.UNCERTAIN),
    "interview": (Status.INTERVIEW,),
    "closed": (Status.REJECTED,),
    "skipped": (Status.SKIPPED,),
}
_VIEWS_WITH_CV = {"pending", "applied", "interview"}

ACTIONS: dict[str, Callable[[sqlite3.Connection, int], JobRow]] = {
    "applied": db.mark_applied,
    "undo_applied": lambda conn, job_id: db.mark_applied(conn, job_id, undo=True),
    "not_interested": db.mark_not_interested,
    "reopen": db.reopen,
    "interview": lambda conn, job_id: db.set_outcome(conn, job_id, Status.INTERVIEW),
    "rejected": lambda conn, job_id: db.set_outcome(conn, job_id, Status.REJECTED),
}


def request_allowed(
    host: str | None, origin: str | None, content_type: str | None, port: int, *, write: bool
) -> bool:
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    if host not in hosts:
        return False
    if not write:
        return True
    same_origin = origin in {f"http://{h}" for h in hosts}
    return same_origin and (content_type or "").startswith("application/json")


def _since_24h() -> str:
    return (datetime.now(UTC) - timedelta(hours=24)).isoformat(timespec="seconds")


def place(row: JobRow, rules: RuleSet) -> str:
    """'remote' (100 % from home), 'national' (on-site or hybrid in the user's area) or 'abroad'."""
    if row.remote:
        return "remote"
    return "national" if rules.in_local_area(row.location) else "abroad"


def job_dict(
    row: JobRow,
    advice: ResumeAdvice | None,
    new_since: str,
    where: str = "",
    twin: JobRow | None = None,
) -> dict:
    cv = None
    if advice is not None:
        cv = {
            "file": advice.filename,
            "label": advice.label,
            "path": str(advice.path),
            "exists": advice.path.exists(),
        }
    return {
        "id": row.id,
        "title": row.title,
        "company": row.company,
        "location": row.location,
        "url": row.url,
        "source": row.source,
        "family": row.role_family,
        "status": row.status.value,
        "reason": row.status_reason,
        "first_seen": row.first_seen_at,
        "updated": row.updated_at,
        "new": row.status == Status.DISCOVERED and row.first_seen_at >= new_since,
        "place": where,
        "cv": cv,
        # An opening already applied to under another source or location (applied_twins).
        "twin": {"id": twin.id, "title": twin.title, "company": twin.company} if twin else None,
    }


def list_view(conn: sqlite3.Connection, view: str) -> list[dict]:
    rows = [r for s in VIEWS[view] for r in db.list_jobs(conn, status=s, limit=5000)]
    if view != "pending":  # pending: newest first (list_jobs order); the rest: latest change
        rows.sort(key=lambda r: r.updated_at, reverse=True)
    search_rules = load_search_rules()
    advice = daily.resume_advice(conn, search_rules, rows) if view in _VIEWS_WITH_CV else {}
    twins = applied_twins(rows, db.applied_jobs(conn)) if view == "pending" else {}
    since = _since_24h()
    rules = RuleSet(search_rules)
    return [job_dict(r, advice.get(r.id), since, place(r, rules), twins.get(r.id)) for r in rows]


def summary(conn: sqlite3.Connection) -> dict:
    counts = db.count_by_status(conn)
    last = db.last_search_at(conn)
    return {
        "counts": {
            **{v: sum(counts.get(s, 0) for s in st) for v, st in VIEWS.items()},
            "decisions": len(signals.pending(conn)),
        },
        "new": len(db.new_matches_since(conn, _since_24h())),
        "last_search": last.isoformat() if last else None,
        # Filter chips of the page, in search.yaml order
        "families": daily.family_labels(),
    }


def decisions_view(conn: sqlite3.Connection) -> list[dict]:
    """grill-me questions the daily run queued (tab "Decisiones")."""
    return [asdict(d) for d in signals.pending(conn)]


def apply_action(conn: sqlite3.Connection, job_id: int, action: str) -> dict:
    """Raises KeyError (no such job), InvalidTransition, or ValueError (unknown action)."""
    if action not in ACTIONS:
        raise ValueError(action)
    row = ACTIONS[action](conn, job_id)
    return job_dict(row, None, _since_24h())


@dataclass
class Discovery:
    running: bool = False
    done: int = 0
    total: int = 0
    current: str = ""
    new: int = 0
    issues: list[tuple[str, str]] = field(default_factory=list)
    error: str = ""
    finished_at: str | None = None


class Panel:
    def __init__(self, db_path: Path, client_factory: Callable[[], HttpClient], port: int) -> None:
        self.db_path = db_path
        self.client_factory = client_factory
        self.port = port
        self.discovery = Discovery()
        self.last_request = time.monotonic()
        self._lock = threading.Lock()

    def connect(self) -> sqlite3.Connection:
        return db.connect(self.db_path)

    def start_discovery(self) -> bool:
        with self._lock:
            if self.discovery.running:
                return False
            self.discovery = Discovery(running=True)
        threading.Thread(target=self._discover, args=(self.discovery,), daemon=True).start()
        return True

    def _discover(self, state: Discovery) -> None:
        def progress(name: str, _report: object, done: int, total: int) -> None:
            state.done, state.total, state.current = done, total, name

        conn = self.connect()
        try:
            with self.client_factory() as client:
                new_jobs, results, _ = daily.run_all(conn, client, progress)
            state.new = len(new_jobs)
            state.issues = daily.attention_needed(results)
        except Exception as exc:  # shown in the panel; the scheduled run is unaffected
            log.exception("discovery failed")
            state.error = f"{type(exc).__name__}: {exc}"
        finally:
            conn.close()
            state.finished_at = db.utc_now()
            state.running = False


class _Handler(BaseHTTPRequestHandler):
    panel: Panel  # set by serve() on a subclass

    def do_GET(self) -> None:
        self.panel.last_request = time.monotonic()
        if not request_allowed(self.headers.get("Host"), None, None, self.panel.port, write=False):
            return self._json({"error": "host"}, HTTPStatus.FORBIDDEN)
        path, _, query = self.path.partition("?")
        if path == "/":
            return self._file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        if path == "/favicon.ico":
            return self._file(STATIC_DIR / "jobbot.ico", "image/x-icon")
        if path == "/api/ping":
            return self._json({"app": "jobbot"})
        if path == "/api/summary":
            with self._conn() as conn:
                data = summary(conn)
            return self._json({**data, "discovery": asdict(self.panel.discovery)})
        if path == "/api/jobs":
            view = parse_qs(query).get("view", ["pending"])[0]
            if view not in VIEWS:
                return self._json({"error": "view"}, HTTPStatus.BAD_REQUEST)
            with self._conn() as conn:
                return self._json({"jobs": list_view(conn, view)})
        if path == "/api/decisions":
            with self._conn() as conn:
                return self._json({"decisions": decisions_view(conn)})
        if path.startswith("/cv/") and _CV_NAME.match(name := path.removeprefix("/cv/")):
            return self._file(paths.resumes_dir() / name, "application/pdf")
        return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        self.panel.last_request = time.monotonic()
        headers = self.headers
        allowed = request_allowed(
            headers.get("Host"),
            headers.get("Origin"),
            headers.get("Content-Type"),
            self.panel.port,
            write=True,
        )
        body = self.rfile.read(int(headers.get("Content-Length") or 0))
        if not allowed:
            return self._json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
        if self.path == "/api/discover":
            return self._json({"started": self.panel.start_discovery()})
        if decision := _DECISION.match(self.path):
            return self._answer_decision(int(decision[1]), body)
        match = _JOB_ACTION.match(self.path)
        if not match:
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        job_id, action = int(match[1]), match[2]
        try:
            with self._conn() as conn:
                job = apply_action(conn, job_id, action)
        except KeyError:
            return self._json({"error": f"La vacante #{job_id} no existe."}, HTTPStatus.NOT_FOUND)
        except InvalidTransition:
            message = f"La vacante #{job_id} ya cambió de estado; recarga la lista."
            return self._json({"error": message}, HTTPStatus.CONFLICT)
        except ValueError:
            return self._json({"error": "acción desconocida"}, HTTPStatus.BAD_REQUEST)
        log.info("job %s: %s", job_id, action)
        return self._json({"job": job})

    def _answer_decision(self, decision_id: int, body: bytes) -> None:
        try:
            choice = json.loads(body or b"{}").get("answer", "")
            with self._conn() as conn:
                result = signals.answer(conn, decision_id, choice)
        except KeyError:
            return self._json({"error": "Esa decisión ya no está pendiente."}, HTTPStatus.CONFLICT)
        except (ValueError, AttributeError):
            return self._json({"error": "opción desconocida"}, HTTPStatus.BAD_REQUEST)
        log.info("decision %s: %s", decision_id, choice)
        return self._json({"result": result})

    def _conn(self) -> _Closing:
        return _Closing(self.panel.connect())

    def _json(self, data: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        self._send(json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json", status)

    def _file(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        self._send(path.read_bytes(), content_type)

    def _send(self, body: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        log.debug("%s %s", self.address_string(), format % args)


class _Closing:
    """`with` for a sqlite3 connection that closes it (sqlite3's own `with` only commits)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        return self.conn

    def __exit__(self, *_: object) -> None:
        self.conn.close()


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR would let a second panel bind the same port silently.
    allow_reuse_address = sys.platform != "win32"


def _setup_logging() -> None:
    log_path = paths.logs_dir() / "panel.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request is just noise
    # Without a console (jobbot-panel.exe) there is no stdout/stderr: send them to the log.
    if sys.stdout is None or sys.stderr is None:
        stream = open(log_path, "a", encoding="utf-8")  # noqa: SIM115 - lives with the process
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream


def _panel_running(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}api/ping", timeout=2) as response:
            return json.load(response).get("app") == "jobbot"
    except (OSError, ValueError):
        return False


def _shutdown_when_idle(server: _Server, panel: Panel) -> None:
    while True:
        time.sleep(30)
        idle = time.monotonic() - panel.last_request
        if idle > IDLE_SHUTDOWN_S and not panel.discovery.running:
            log.info("no requests for %.0f s: stopping", idle)
            server.shutdown()
            return


def serve(
    db_path: Path,
    client_factory: Callable[[], HttpClient],
    *,
    port: int,
    open_browser: bool = True,
) -> int:
    _setup_logging()
    url = f"http://127.0.0.1:{port}/"
    panel = Panel(db_path, client_factory, port)
    handler = type("Handler", (_Handler,), {"panel": panel})
    try:
        server = _Server(("127.0.0.1", port), handler)
    except OSError:
        if _panel_running(url):  # second click on the shortcut: show the running panel
            if open_browser:
                webbrowser.open(url)
            return 0
        message = f"El puerto {port} lo usa otro programa; cambia panel.port en settings.yaml."
        log.error(message)
        print(message)
        if sys.platform == "win32":
            daily.notify_windows("JobBot: no se pudo abrir el panel", message)
        return 1
    threading.Thread(target=_shutdown_when_idle, args=(server, panel), daemon=True).start()
    log.info("panel on %s (db: %s)", url, db_path)
    print(f"Panel en {url}  (Ctrl+C para cerrarlo; sin uso por 10 min se cierra solo)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
