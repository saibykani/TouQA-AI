"""Resilient HTTP client shared by the Spira and Jira adapters.

Policy:
* Reads (and POST searches flagged ``safe_retry``) are retried on connection errors,
  timeouts, 429 and 502/503/504 using exponential backoff with jitter, honouring Retry-After.
* Writes are NEVER retried automatically. A timeout or dropped connection on a write raises
  ``OutcomeUnknownError`` so the caller can reconcile before any resubmission.
* Every request is pinned to the configured base URL host (SSRF defence in depth).
* Credentials are never logged; log lines pass through the redaction filter.
"""
from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings
from app.security.netguard import same_origin
from app.security.redaction import redact_text

log = logging.getLogger("touqa.http")

RETRYABLE_STATUS = {429, 502, 503, 504}


class IntegrationError(Exception):
    """Base error. ``user_message`` is safe to display; it never contains credentials."""

    retryable = False

    def __init__(self, user_message: str, *, status_code: int | None = None, detail: str | None = None):
        super().__init__(user_message)
        self.user_message = user_message
        self.status_code = status_code
        self.detail = redact_text(detail or "")[:2000]


class IntegrationAuthError(IntegrationError):
    pass


class IntegrationPermissionError(IntegrationError):
    pass


class IntegrationNotFoundError(IntegrationError):
    pass


class IntegrationValidationError(IntegrationError):
    pass


class IntegrationRateLimitError(IntegrationError):
    retryable = True


class IntegrationServerError(IntegrationError):
    retryable = True


class IntegrationNetworkError(IntegrationError):
    retryable = True


class OutcomeUnknownError(IntegrationError):
    """A write may or may not have been applied by the remote system."""


class OperationCancelled(Exception):
    pass


@dataclass
class HttpResponse:
    status_code: int
    data: Any
    headers: dict[str, str]
    text: str


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


class ResilientClient:
    def __init__(
        self,
        base_url: str,
        *,
        headers: dict[str, str] | None = None,
        auth: httpx.Auth | tuple[str, str] | None = None,
        platform: str = "external",
        transport: httpx.BaseTransport | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        backoff_base: float | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        s = get_settings()
        self.base_url = base_url.rstrip("/")
        self.platform = platform
        self.max_retries = s.http_max_retries if max_retries is None else max_retries
        self.backoff_base = s.http_backoff_base_seconds if backoff_base is None else backoff_base
        self._sleep = sleep
        self._client = httpx.Client(
            base_url=self.base_url,
            headers=headers or {},
            auth=auth,
            timeout=httpx.Timeout(timeout or s.http_timeout_seconds, connect=10.0),
            verify=s.verify_tls,
            follow_redirects=False,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(retry_after, 60.0)
        return min(self.backoff_base * (2 ** attempt) + random.uniform(0, self.backoff_base), 30.0)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        content: bytes | None = None,
        files: Any = None,
        headers: dict[str, str] | None = None,
        safe_retry: bool | None = None,
        cancel_check: Callable[[], bool] | None = None,
        expect_json: bool = True,
    ) -> HttpResponse:
        method = method.upper()
        is_read = method in {"GET", "HEAD", "OPTIONS"}
        retry_allowed = is_read if safe_retry is None else safe_retry
        url = path if path.startswith("http") else f"{self.base_url}/{path.lstrip('/')}"
        if not same_origin(self.base_url, url):
            raise IntegrationValidationError("Refusing to send a request outside the configured integration host")

        attempt = 0
        while True:
            if cancel_check and cancel_check():
                raise OperationCancelled()
            try:
                resp = self._client.request(
                    method, url, params=params, json=json, content=content, files=files, headers=headers
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                kind = "timed out" if isinstance(exc, httpx.TimeoutException) else "failed to connect"
                if not retry_allowed:
                    if method in {"POST", "PUT", "PATCH", "DELETE"} and not isinstance(exc, httpx.ConnectError):
                        raise OutcomeUnknownError(
                            f"The {self.platform} request {kind} before a response arrived. The record may or "
                            "may not have been created; TouQA will reconcile before any retry.",
                            detail=str(exc),
                        ) from exc
                    raise IntegrationNetworkError(f"{self.platform} request {kind}: {exc.__class__.__name__}") from exc
                if attempt >= self.max_retries:
                    raise IntegrationNetworkError(
                        f"{self.platform} request {kind} after {attempt + 1} attempts", detail=str(exc)
                    ) from exc
                delay = self._backoff(attempt, None)
                log.warning("%s %s %s; retrying in %.1fs", self.platform, method, kind, delay)
                self._sleep(delay)
                attempt += 1
                continue

            if resp.status_code in RETRYABLE_STATUS and retry_allowed and attempt < self.max_retries:
                delay = self._backoff(attempt, _parse_retry_after(resp.headers.get("Retry-After")))
                log.warning("%s %s returned %s; retrying in %.1fs", self.platform, method, resp.status_code, delay)
                self._sleep(delay)
                attempt += 1
                continue
            return self._handle(resp, expect_json)

    def _handle(self, resp: httpx.Response, expect_json: bool) -> HttpResponse:
        text = resp.text or ""
        status = resp.status_code
        if 200 <= status < 300:
            data: Any = None
            if expect_json and text.strip():
                try:
                    data = resp.json()
                except ValueError:
                    data = text
            return HttpResponse(status, data, dict(resp.headers), text)

        detail = text[:2000]
        p = self.platform.capitalize()
        if status == 401:
            raise IntegrationAuthError(
                f"{p} rejected the credentials (HTTP 401). Check the username and API key/token.",
                status_code=status, detail=detail,
            )
        if status == 403:
            raise IntegrationPermissionError(
                f"{p} denied access (HTTP 403). The account may lack permission for this project or operation.",
                status_code=status, detail=detail,
            )
        if status == 404:
            raise IntegrationNotFoundError(f"{p} resource not found (HTTP 404).", status_code=status, detail=detail)
        if status == 429:
            raise IntegrationRateLimitError(f"{p} rate limit reached (HTTP 429). Try again shortly.", status_code=status, detail=detail)
        if status in (400, 409, 422):
            raise IntegrationValidationError(
                f"{p} rejected the request (HTTP {status}): {self._extract_message(text)}", status_code=status, detail=detail
            )
        if 300 <= status < 400:
            raise IntegrationValidationError(
                f"{p} responded with a redirect (HTTP {status}). Check the configured base URL.", status_code=status, detail=detail
            )
        raise IntegrationServerError(f"{p} server error (HTTP {status}).", status_code=status, detail=detail)

    @staticmethod
    def _extract_message(text: str) -> str:
        import json as _json

        try:
            body = _json.loads(text)
        except ValueError:
            return redact_text(text.strip()[:300]) or "no details"
        if isinstance(body, dict):
            for key in ("Message", "message", "errorMessages", "errors", "ExceptionMessage", "error"):
                if key in body and body[key]:
                    return redact_text(str(body[key])[:500])
        return redact_text(str(body)[:300])
