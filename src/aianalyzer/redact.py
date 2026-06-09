"""Best-effort redaction of obvious secrets in session text."""
from __future__ import annotations

import re
from typing import Final

_PATTERNS: Final[list[tuple[re.Pattern[str], str]]] = [
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{20,}\b"), "Bearer [REDACTED_BEARER]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"(?i)(password|passwd|secret|api[_\-]?key)\s*=\s*\S+"),
     r"\1=[REDACTED_PASSWORD]"),
    (re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
     "[REDACTED_EMAIL]"),
]


def redact(text: str) -> str:
    """Replace obvious secrets with stable placeholders. Idempotent."""
    if not text:
        return text
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text
