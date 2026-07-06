"""Guardrail Interceptor — detects an explicit request for a (specific) human
broker and produces a bypass decision, BEFORE the Coordinator reasons
(GuardrailPort.check, Architecture.md §8 Iteración 2; sequence §7.5).

Rules are hardcoded in this iteration by design; Iteración 7 replaces them with
`GuardrailConfigPort.get_active_rules(organizationId)` backed by the
Configuration Store. Lead content is treated strictly as data to match against
patterns — never as instructions (Agentic_System §6, prompt-injection control).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.shared.domain.base import ValueObject

#: Patterns that capture a *named* broker request: "¿Está María?", "quiero
#: hablar con María", "pásame con la señora María", "busco a María".
_NAMED_BROKER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:est[aá])\s+(?:el\s+|la\s+)?(?:se[ñn]or(?:a)?\s+|sr\.?\s+|sra\.?\s+)?"
        r"(?P<name>[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+)\s*\?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:hablar|comunicar(?:me)?|contactar(?:me)?)\s+con\s+"
        r"(?:el\s+|la\s+)?(?:se[ñn]or(?:a)?\s+|sr\.?\s+|sra\.?\s+)?"
        r"(?P<name>[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+)",
    ),
    re.compile(
        r"(?:p[aá]same|comun[ií]came|con[eé]ctame)\s+con\s+"
        r"(?:el\s+|la\s+)?(?:se[ñn]or(?:a)?\s+|sr\.?\s+|sra\.?\s+)?"
        r"(?P<name>[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+)",
        re.IGNORECASE,
    ),
    re.compile(r"busco\s+a\s+(?P<name>[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+)"),
)

#: Generic "I want a human" requests — transfer without a named broker.
_GENERIC_HUMAN_PATTERN = re.compile(
    r"(?:hablar|comunicar(?:me)?|contactar(?:me)?|p[aá]same|ati[eé]ndame)\s*"
    r"(?:con|a)?\s*(?:un[a]?\s+)?(?:asesor|agente|humano|persona\s+real|broker|vendedor)",
    re.IGNORECASE,
)

#: Words the named patterns can capture that are NOT broker names.
_NAME_STOPWORDS = frozenset(
    {"un", "una", "el", "la", "alguien", "ustedes", "usted", "disponible", "abierto"}
)


@dataclass(frozen=True)
class BypassDecision(ValueObject):
    """The Coordinator must NOT generate a conversational reply this turn —
    ownership transfers immediately (scenario 8 of the E14 matrix)."""

    broker_requested: str | None
    matched_text: str


class GuardrailInterceptor:
    """Runs BEFORE any Coordinator LLM reasoning. Returns a BypassDecision when
    the lead explicitly asked for a human/broker, else None (continue)."""

    def check(self, message: str) -> BypassDecision | None:
        for pattern in _NAMED_BROKER_PATTERNS:
            match = pattern.search(message)
            if match:
                name = match.group("name").strip()
                if name.lower() in _NAME_STOPWORDS:
                    continue
                return BypassDecision(broker_requested=name, matched_text=match.group(0))

        generic = _GENERIC_HUMAN_PATTERN.search(message)
        if generic:
            return BypassDecision(broker_requested=None, matched_text=generic.group(0))
        return None
