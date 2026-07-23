# app/shared/infrastructure/pii_redaction.py
"""Scrubs PII from text before it leaves the process toward the external
LangSmith SaaS (traces of conversation brain / extractor / narrator calls
carry real lead names, phone numbers and emails). Regex-based and
deliberately conservative — false positives (over-redacting) are safe for a
debugging trace; false negatives are the risk this exists to avoid."""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# Matches +51 987 654 321 / 987654321 / (01) 555-1234 / 555-1234 style runs of
# 6+ digits with optional separators and an optional leading country code —
# generic enough for Peru (+51 9XXXXXXXX) and common landline formats without
# also matching short numbers like bedroom counts or budgets.
_PHONE_RE = re.compile(r"(?:\+?\d{1,3}[\s.-]?)?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}")


def redact_pii(text: str | None) -> str | None:
    if not text:
        return text
    redacted = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    redacted = _PHONE_RE.sub("[REDACTED_PHONE]", redacted)
    return redacted


def redact_pii_deep(value: object) -> object:
    """Recursively walks dicts/lists/tuples, redacting every string found.

    The per-call-site `process_inputs`/`process_outputs` hooks (Tasks 4-7)
    know their payload's exact shape and redact specific fields. LangSmith's
    client-level `hide_inputs`/`hide_outputs` hooks (wired in
    `configure_langsmith_tracing`) receive arbitrary run payloads instead —
    notably LangGraph's own auto-generated runs (`ainvoke`, the `respond`
    node), which carry the full conversational state and are NOT covered by
    any `@traceable` site's redaction. This is the catch-all for those."""
    if isinstance(value, str):
        return redact_pii(value)
    if isinstance(value, dict):
        return {key: redact_pii_deep(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(redact_pii_deep(item) for item in value)
    return value
