"""Redaction of secrets from logs, audit details, and stored request summaries."""
from __future__ import annotations

import logging
import re
from typing import Any

SENSITIVE_KEYS = {
    "authorization", "api-key", "api_key", "apikey", "password", "passwd", "secret",
    "token", "api_token", "access_token", "refresh_token", "x-api-key", "cookie",
    "set-cookie", "rsstoken", "rss_token", "client_secret", "private_key", "binarydata",
}
REDACTED = "[REDACTED]"

_PATTERNS = [
    # Authorization headers
    (re.compile(r"(?i)(authorization\s*[:=]\s*)(basic|bearer)\s+[A-Za-z0-9._~+/=-]+"), r"\1\2 " + REDACTED),
    # Query-string credentials used by Spira (?username=x&api-key={...})
    (re.compile(r"(?i)(api[-_]?key=)[^&\s\"']+"), r"\1" + REDACTED),
    (re.compile(r"(?i)(password=)[^&\s\"']+"), r"\1" + REDACTED),
    (re.compile(r"(?i)(token=)[^&\s\"']+"), r"\1" + REDACTED),
    # Spira RSS tokens are GUIDs wrapped in braces
    (re.compile(r"\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}"), REDACTED),
    # Anthropic / OpenAI style keys
    (re.compile(r"sk-(ant-)?[A-Za-z0-9_-]{16,}"), REDACTED),
    # Atlassian API tokens
    (re.compile(r"ATATT[A-Za-z0-9_=-]{20,}"), REDACTED),
]


def redact_text(text: str) -> str:
    if not text:
        return text
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


def redact(value: Any, _depth: int = 0) -> Any:
    """Recursively redact dict keys known to hold secrets and secret-looking strings."""
    if _depth > 12:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(k, str) and k.lower() in SENSITIVE_KEYS:
                out[k] = REDACTED if v not in (None, "") else v
            else:
                out[k] = redact(v, _depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(v, _depth + 1) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


class RedactingFilter(logging.Filter):
    """Logging filter that scrubs secrets from every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # pragma: no cover - malformed format args
            return True
        record.msg = redact_text(msg)
        record.args = None
        return True
