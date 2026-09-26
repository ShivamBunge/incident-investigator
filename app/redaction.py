"""Redact obvious tokens/secrets before evidence is sent to an external model
(spec Section 12 security requirements)."""

from __future__ import annotations

import re

_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Authorization headers first, so "Bearer <token>" is fully consumed
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]{16,}\b"), "Bearer <redacted>"),
    # key=value / key: value style assignments for secret-ish keys; the
    # lookahead skips "Bearer" values already handled by the pattern above
    (
        re.compile(
            r"(?i)\b(api[_-]?key|token|secret|password|passwd|authorization)\b\s*[=:]\s*\"?(?!Bearer\b)[^\s\",]+"
        ),
        r"\1=<redacted>",
    ),
    # common token prefixes (OpenAI, OpenRouter, GitHub, Slack)
    (
        re.compile(
            r"\b(?:sk-[A-Za-z0-9_-]{16,}|sk-or-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|"
            r"gho_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})\b"
        ),
        "<redacted-token>",
    ),
    # PEM private keys
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
        "<redacted-private-key>",
    ),
]


def redact_text(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_mapping(value):
    """Recursively redact every string value inside dicts/lists."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: redact_mapping(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_mapping(v) for v in value]
    return value