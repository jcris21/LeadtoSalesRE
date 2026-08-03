"""G8 identity capture (docs/e2e-manual-chat-checklist.md): deterministic
name/DNI extractor feeding the Coordinator's identity gate. Same contract as
the qualification extractors — recognition only: a message that does not
clearly carry a name comes back None, never a guessed identity.

Two recognition paths, tried in order:
1. Explicit introduction ("me llamo …", "mi nombre es …", "soy …").
2. Bare name reply — the whole message IS the name (plus an optional DNI),
   which is what the welcome prompt asks the contact to send.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The Coordinator's reply while a conversation has no linked Lead: the
#: welcome message asks the contact to leave their name (G8 flow). US-218:
#: DNI is deliberately NOT mentioned here — it is the one identity field
#: deferred past the first turn (HU_Calificacion_Recomendacion.md US-218),
#: requested later via `REPROMPT_DNI` once a recommendation/value moment has
#: been shown. Name stays mandatory on turn 1: it is the minimal identifier
#: `LeadSyncAdapter.create_lead`/wacrm's `/deals` contract actually requires
#: alongside the channel's own phone (`contact_reference`, already known
#: before any reply — see wacrm_client.py's `create_lead` docstring).
REPROMPT_IDENTITY = (
    "¡Hola! Soy el asistente del equipo de asesores. Para poder ayudarte, "
    "¿me compartes tu nombre completo?"
)

#: US-218 deferred ask: shown only once the conversation has reached the
#: RECOMMENDATION state (a Top-3/value moment has already been delivered).
#: Additive, never blocking — a missing DNI must not stop qualification,
#: scheduling or the conversational reply (unlike the name gate above, which
#: legitimately blocks until a Lead exists to attach a reply to).
REPROMPT_DNI = (
    "Para dejar tu perfil completo de cara a coordinar una visita, "
    "¿me compartes tu DNI? Si prefieres, podemos seguir sin él por ahora."
)


@dataclass(frozen=True)
class IdentityCapture:
    """What one message contributed to identity: a name, optionally a DNI."""

    full_name: str
    dni: str | None = None


#: Peruvian DNI: exactly 8 digits standing alone — a 9-digit mobile number or
#: a full +51 phone never matches, so a phone can't be captured as a DNI.
_DNI_RE = re.compile(r"(?<!\d)\d{8}(?!\d)")

_TRIGGER_RE = re.compile(r"\b(?:me llamo|mi nombre es|soy)\s+(.*)", re.IGNORECASE)

#: A single name word: letters (with Spanish accents), apostrophe or hyphen.
_NAME_WORD_RE = re.compile(r"[a-záéíóúüñ'-]+", re.IGNORECASE)

#: Words that end a name run / disqualify a bare message as being a name.
_NOT_NAME_WORDS = frozenset(
    {
        "hola", "buenas", "buenos", "dias", "días", "tardes", "noches",
        "estoy", "soy", "busco", "buscando", "quiero", "quisiera", "necesito",
        "gracias", "por", "favor", "si", "sí", "no", "ok",
        "que", "qué", "un", "una", "el", "la", "los", "las", "de", "del",
        "y", "o", "en", "es", "mi", "mis", "me", "con", "para",
        "llamo", "nombre", "dni", "numero", "número",
        "telefono", "teléfono", "celular",
        "comprar", "alquilar", "departamento", "casa", "depa",
        "zona", "presupuesto", "interesa",
    }
)

_MAX_NAME_WORDS = 4


def _capitalize(word: str) -> str:
    return word[:1].upper() + word[1:]


def _collect_name_run(tokens: list[str]) -> str | None:
    """Leading run of name words after an explicit trigger. Punctuation or a
    non-name word ("y", "mi", …) ends the run — that's how the name stops
    before a trailing 'y mi DNI es …' clause."""
    words: list[str] = []
    for raw in tokens:
        word = raw.strip(",.;:!?¡¿")
        if (
            not word
            or not _NAME_WORD_RE.fullmatch(word)
            or word.lower() in _NOT_NAME_WORDS
        ):
            break
        words.append(_capitalize(word))
        if word != raw or len(words) == _MAX_NAME_WORDS:
            break
    return " ".join(words) if words else None


def _bare_name(text: str) -> str | None:
    """The whole message is a name (2–4 clean words), optionally with a DNI
    token. Any punctuation, sentence word or extra content disqualifies it —
    a greeting or a search phrase must never become somebody's name."""
    words: list[str] = []
    for raw in text.split():
        if _DNI_RE.fullmatch(raw):
            continue
        if not _NAME_WORD_RE.fullmatch(raw) or raw.lower() in _NOT_NAME_WORDS:
            return None
        words.append(_capitalize(raw))
    if not 2 <= len(words) <= _MAX_NAME_WORDS:
        return None
    return " ".join(words)


def extract_identity(text: str) -> IdentityCapture | None:
    """Deterministic name/DNI recognition over one lead message."""
    stripped = text.strip()
    if not stripped:
        return None
    match = _TRIGGER_RE.search(stripped)
    if match is not None:
        name = _collect_name_run(match.group(1).split())
    else:
        name = _bare_name(stripped)
    if name is None:
        return None
    dni_match = _DNI_RE.search(stripped)
    return IdentityCapture(full_name=name, dni=dni_match.group(0) if dni_match else None)


def extract_dni(text: str) -> str | None:
    """US-218 deferred capture: once identity (name) is already established and
    a value moment has been shown, a later message may carry just the DNI on
    its own, with no name alongside it. Reuses the same 8-digit-standalone
    recognition `extract_identity` uses, without requiring a name in the same
    message."""
    match = _DNI_RE.search(text.strip())
    return match.group(0) if match else None
