"""Read-only Gmail access (ADR-012): OAuth installed-app flow + Gmail REST API via HttpClient.

Scope is gmail.readonly: the bot can search and read messages, never send, delete or modify.
Credentials and token live in profile/private/ (git-ignored). See docs/platforms/email-alerts.md.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from jobbot.core.http import HttpClient
from jobbot.discovery.base import SourceNotConfigured

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
API = "https://gmail.googleapis.com/gmail/v1/users/me"
SETUP_DOC = "docs/platforms/email-alerts.md"


@dataclass(frozen=True)
class MailMessage:
    id: str
    subject: str
    sender: str
    text: str
    html: str


MISSING_EXTRA = "falta el extra de Gmail: instálalo con `uv sync --extra gmail`"


def login(credentials_file: Path, token_file: Path) -> None:
    """Open the browser for consent and store the refreshable token."""
    if not credentials_file.exists():
        raise SourceNotConfigured(f"falta {credentials_file.name}; ver {SETUP_DOC}")
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise SourceNotConfigured(MISSING_EXTRA) from exc
    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), SCOPES)
    credentials = flow.run_local_server(port=0, open_browser=True)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(credentials.to_json(), encoding="utf-8")


def access_token(credentials_file: Path, token_file: Path) -> str:
    """Valid access token, refreshed when expired. Raises SourceNotConfigured if login is due."""
    if not credentials_file.exists():
        raise SourceNotConfigured(f"falta {credentials_file.name}; ver {SETUP_DOC}")
    if not token_file.exists():
        raise SourceNotConfigured("falta autorizar Gmail: corre `uv run jobbot gmail-login`")
    try:
        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError as exc:
        raise SourceNotConfigured(MISSING_EXTRA) from exc
    credentials = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if credentials.valid:
        return credentials.token
    if not (credentials.expired and credentials.refresh_token):
        raise SourceNotConfigured("token de Gmail inválido: corre `uv run jobbot gmail-login`")
    try:
        credentials.refresh(Request())
    except RefreshError as exc:
        raise SourceNotConfigured(
            "token de Gmail vencido o revocado: corre `uv run jobbot gmail-login`"
        ) from exc
    token_file.write_text(credentials.to_json(), encoding="utf-8")
    return credentials.token


class GmailClient:
    def __init__(self, http: HttpClient, token: Callable[[], str]) -> None:
        self._http = http
        self._token = token
        self._cached_token: str | None = None

    def _get(self, url: str) -> Any:
        if self._cached_token is None:
            self._cached_token = self._token()
        return self._http.get_json(url, headers={"Authorization": f"Bearer {self._cached_token}"})

    def profile_email(self) -> str:
        return self._get(f"{API}/profile").get("emailAddress", "")

    def search(self, query: str, max_messages: int) -> list[str]:
        ids: list[str] = []
        page_token = ""
        while len(ids) < max_messages:
            url = f"{API}/messages?q={quote(query)}&maxResults={min(100, max_messages)}"
            if page_token:
                url += f"&pageToken={page_token}"
            data = self._get(url)
            ids += [m["id"] for m in data.get("messages") or []]
            page_token = data.get("nextPageToken", "")
            if not page_token:
                break
        return ids[:max_messages]

    def headers(
        self, message_id: str, names: tuple[str, ...] = ("From", "Subject", "Date")
    ) -> dict[str, str]:
        """Only the requested headers (format=metadata): no message body is downloaded."""
        query = "&".join(f"metadataHeaders={name}" for name in names)
        data = self._get(f"{API}/messages/{message_id}?format=metadata&{query}")
        return {h["name"]: h["value"] for h in (data.get("payload") or {}).get("headers") or []}

    def get(self, message_id: str) -> MailMessage:
        data = self._get(f"{API}/messages/{message_id}?format=full")
        payload = data.get("payload") or {}
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers") or []}
        parts: dict[str, list[str]] = {"text/plain": [], "text/html": []}
        _collect_parts(payload, parts)
        return MailMessage(
            id=message_id,
            subject=headers.get("subject", ""),
            sender=headers.get("from", ""),
            text="\n".join(parts["text/plain"]),
            html="\n".join(parts["text/html"]),
        )


def _collect_parts(part: dict[str, Any], out: dict[str, list[str]]) -> None:
    mime = part.get("mimeType", "")
    data = (part.get("body") or {}).get("data")
    if mime in out and data:
        out[mime].append(_decode(data))
    for child in part.get("parts") or []:
        _collect_parts(child, out)


def _decode(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
