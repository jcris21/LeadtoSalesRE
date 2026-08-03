"""Defense-in-depth against hallucinated property links (US-hallucination-fix,
2026-07-24 incident: CW-DEMO-1784860599/MSG-0010 reached the lead with 2 fake
listing URLs the LLM invented). `search_diagnostics` and the hardened
`DEFAULT_SYSTEM_PROMPT` (prompts.py) close the root cause, but a future prompt
or model regression could reopen it — this is the last gate before a reply
reaches the lead: any URL it contains must be a real, known property link for
the organization, or the whole message is swapped for a safe fallback."""

from __future__ import annotations

import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.recommendation.infrastructure.repository import PropertyRepository

_URL_PATTERN = re.compile(r"https?://\S+")
_URL_TRAILING_PUNCTUATION = ".,;:)]}\"'"

FALLBACK_REPLY = (
    "Estoy verificando esa información con el equipo antes de compartirte un enlace: "
    "te confirmo en un momento."
)

#: 2026-07-25 follow-up incident: a reply with three fake listings (prices,
#: areas, addresses) but *no* URL sailed straight past the check above. This
#: function never sees the real `RecommendationService`-composed Top-3 (that
#: message is emitted directly from `recommendation.wiring`, not through
#: `guard_reply`) — so anything shaped like a numbered property listing that
#: reaches here is, by construction, the conversational LLM's own free text.
#: Two independent signals reduce false positives on a normal reply that
#: merely echoes the lead's own budget: a numbered/bulleted list (>=2 items)
#: *and* at least 2 price-or-area tokens spread across the message.
_LISTING_ITEM_PATTERN = re.compile(r"^\s*(?:\d+[.):]|[-*•])\s+\S", re.MULTILINE)
_PRICE_OR_AREA_PATTERN = re.compile(
    r"(?:USD|US\$|S/\.?|\$)\s?\d[\d,.]*|\d+\s?m[²2]\b", re.IGNORECASE
)

LISTING_FALLBACK_REPLY = (
    "Estoy confirmando esas opciones con el equipo antes de darte precios y datos "
    "exactos: en un momento te comparto el detalle real."
)


def _looks_like_fabricated_listing(reply: str) -> bool:
    if len(_LISTING_ITEM_PATTERN.findall(reply)) < 2:
        return False
    return len(_PRICE_OR_AREA_PATTERN.findall(reply)) >= 2


async def guard_reply(session: AsyncSession, *, organization_id: uuid.UUID, reply: str) -> str:
    """Last gate before a conversational reply reaches the lead. Returns
    `reply` unchanged unless it either (a) mentions a URL that isn't a real
    property link for `organization_id`, or (b) is shaped like a fabricated
    property listing (numbered items each carrying a price/area) — either
    case swaps in a safe fallback instead of forwarding invented content."""
    urls = _URL_PATTERN.findall(reply)
    if urls:
        known_links: set[str] = set()
        for property in await PropertyRepository(session).list_for_organization(organization_id):
            known_links.update(property.link_references)
        if not all(url.rstrip(_URL_TRAILING_PUNCTUATION) in known_links for url in urls):
            return FALLBACK_REPLY

    if _looks_like_fabricated_listing(reply):
        return LISTING_FALLBACK_REPLY

    return reply
