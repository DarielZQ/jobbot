"""Polite HTTP client: per-host minimum interval, Retry-After, honest User-Agent."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

from jobbot import __version__

RETRYABLE_STATUS = {429, 502, 503, 504}
# The request never reached the server (DNS lookup, refused or timed-out connection), so a
# retry is safe even for POST.
RETRYABLE_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout)
# Google APIs (Gmail) answer some rate limits with 403 instead of 429. Other 403s (a site
# blocking the bot, a missing permission) are final.
GOOGLE_RATE_LIMITS = {"rateLimitExceeded", "userRateLimitExceeded", "RATE_LIMIT_EXCEEDED"}


def user_agent() -> str:
    contact = os.environ.get("JOBBOT_CONTACT_EMAIL", "").strip()
    suffix = f"; contact: {contact}" if contact else ""
    return f"JobBot/{__version__} (job search tool{suffix})"


class HttpClient:
    def __init__(
        self,
        *,
        timeout_s: float = 30,
        min_interval_s: float = 2.0,
        max_retries: int = 3,
        host_min_interval_s: dict[str, float] | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = httpx.Client(
            timeout=timeout_s,
            headers={"User-Agent": user_agent(), "Accept": "application/json"},
            follow_redirects=True,
            transport=transport,
        )
        self._min_interval_s = min_interval_s
        self._host_min_interval_s = host_min_interval_s or {}
        self._max_retries = max_retries
        self._sleep = sleep
        self._last_request_at: dict[str, float] = {}

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get_json(self, url: str, **kwargs: Any) -> Any:
        return self.request("GET", url, **kwargs).json()

    def get_text(self, url: str, accept: str = "*/*", **kwargs: Any) -> str:
        return self.request("GET", url, headers={"Accept": accept}, **kwargs).text

    def post_json(self, url: str, payload: Any, **kwargs: Any) -> Any:
        return self.request("POST", url, json=payload, **kwargs).json()

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        host = urlsplit(url).netloc
        for attempt in range(self._max_retries + 1):
            self._wait_for_host(host)
            try:
                response = self._client.request(method, url, **kwargs)
            except RETRYABLE_ERRORS:
                if attempt == self._max_retries:
                    raise
                self._sleep(_backoff(attempt))
                continue
            self._last_request_at[host] = time.monotonic()
            if not _retryable(response) or attempt == self._max_retries:
                response.raise_for_status()
                return response
            self._sleep(_retry_delay(response, attempt))
        raise AssertionError("unreachable")

    def _wait_for_host(self, host: str) -> None:
        last = self._last_request_at.get(host)
        if last is None:
            return
        interval = self._host_min_interval_s.get(host, self._min_interval_s)
        remaining = interval - (time.monotonic() - last)
        if remaining > 0:
            self._sleep(remaining)


def _retryable(response: httpx.Response) -> bool:
    if response.status_code in RETRYABLE_STATUS:
        return True
    return response.status_code == 403 and bool(_google_reasons(response) & GOOGLE_RATE_LIMITS)


def _google_error(response: httpx.Response) -> dict[str, Any]:
    """The `error` object of a Google API error body, or {} for anything else."""
    try:
        body = response.json()
    except ValueError:
        return {}
    error = body.get("error") if isinstance(body, dict) else None
    return error if isinstance(error, dict) else {}


def _google_reasons(response: httpx.Response) -> set[str]:
    error = _google_error(response)
    items = [*(error.get("errors") or []), *(error.get("details") or [])]
    return {str(item.get("reason", "")) for item in items if isinstance(item, dict)}


def error_detail(response: httpx.Response) -> str:
    """The API's own explanation of an error response, for the report ("" if it gave none)."""
    message = _google_error(response).get("message")
    return str(message)[:200] if message else ""


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After", "")
    if retry_after.isdigit():
        return min(float(retry_after), 300.0)
    return _backoff(attempt)


def _backoff(attempt: int) -> float:
    return 2.0 * (4**attempt)  # 2s, 8s, 32s
