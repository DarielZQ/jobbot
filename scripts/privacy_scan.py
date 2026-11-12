"""Privacy scan: personal data or tool signatures must never reach the repository.

Checks every file git tracks (or would track) and, with --history, every past commit:
- email addresses outside example domains and the job sites' own sender addresses;
- Windows user folders other than the placeholder C:\\Users\\<Usuario>;
- automatic signatures in commit messages ("Generated with", "Co-Authored-By");
- every term of a personal deny-list (--denylist FILE, one term per line): names, places, tools
  you never want mentioned. Keep that file OUTSIDE the repository: it holds the very data it
  protects.

Usage:  uv run python scripts/privacy_scan.py [--history] [--denylist FILE]
Exit code 1 when something is found. Prints file and line, never the deny-listed term itself.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_EMAIL_DOMAINS = (
    "example.invalid",
    "example.com",
    "linkedin.com",
    "indeed.com",
    "computrabajo.com",
    "elempleo.com",
    "correoelempleo.com",
    "torre.ai",
    "users.noreply.github.com",
)
# The local part starts with a letter or digit: "+@pytest.mark" in a diff is not an address.
EMAIL = re.compile(r"(?<![\w.+-])[a-z0-9][\w.+-]*@([\w-]+\.)+[a-z]{2,}", re.I)
USER_PATH = re.compile(
    r"[A-Za-z]:[\\/]+Users[\\/]+(?!<Usuario>|<User>|Public\b)[^\\/\s\"'<>]+", re.I
)
SIGNATURE = re.compile(r"generated with|co-authored-by", re.I)
# This file names those patterns on purpose.
SKIP = {"scripts/privacy_scan.py"}
_DIFF_FILE = re.compile(r"^diff --git a/(\S+) b/")


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [f for f in out.splitlines() if f not in SKIP]


def load_denylist(path: Path | None) -> list[str]:
    if path is None:
        return []
    terms = path.read_text(encoding="utf-8").splitlines()
    return [t.strip() for t in terms if t.strip() and not t.startswith("#")]


def findings(text: str, denylist: list[str]) -> list[str]:
    found = []
    for match in EMAIL.finditer(text):
        domain = match.group(0).rsplit("@", 1)[1].lower()
        if not any(domain == d or domain.endswith("." + d) for d in ALLOWED_EMAIL_DOMAINS):
            found.append(f"correo fuera de los dominios de ejemplo: {match.group(0)}")
    for match in USER_PATH.finditer(text):
        found.append(f"ruta de usuario real: {match.group(0)}")
    for match in SIGNATURE.finditer(text):
        found.append(f"firma automática: {match.group(0)}")
    lowered = text.lower()
    for number, term in enumerate(denylist, 1):
        if term.lower() in lowered:
            found.append(f"término #{number} de la lista personal")
    return found


def scan_files(denylist: list[str]) -> int:
    problems = 0
    for name in tracked_files():
        path = ROOT / name
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, FileNotFoundError):
            continue  # binary files (icons) and files deleted in the working tree
        for number, line in enumerate(lines, 1):
            for problem in findings(line, denylist):
                print(f"{name}:{number}: {problem}")
                problems += 1
    return problems


def scan_history(denylist: list[str]) -> int:
    log = subprocess.run(
        ["git", "log", "--all", "-p", "--format=COMMIT %H%n%an <%ae>%n%cn <%ce>%n%B"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout
    problems = 0
    commit = current = ""
    for line in log.splitlines():
        if line.startswith("COMMIT "):
            commit, current = line[7:15], ""
            continue
        if match := _DIFF_FILE.match(line):
            current = match.group(1)
        if current in SKIP:
            continue
        for problem in findings(line, denylist):
            print(f"historial {commit}: {problem}")
            problems += 1
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--history", action="store_true", help="Revisar también cada commit")
    parser.add_argument("--denylist", type=Path, help="Términos personales, uno por línea")
    args = parser.parse_args()
    denylist = load_denylist(args.denylist)
    problems = scan_files(denylist) + (scan_history(denylist) if args.history else 0)
    print(f"Escaneo de privacidad: {problems} hallazgo(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
