"""On-demand E2E chat simulator (docs/e2e-manual-chat-checklist.md §8): sends
ONE free-text lead message to the Chatwoot webhook — the same entry point the
manual guion in §6 uses — so an operator can type whatever they want, turn by
turn, without hand-writing curl JSON each time.

If `--conversation-id` points at a real Chatwoot conversation and the org has
`OrganizationConfig.chatwoot` configured (see §5.1) AND that Chatwoot account
has its `message_created` webhook registered against our app (one-time setup,
also §5.1), this script posts the lead's own message straight into that
Chatwoot conversation as an incoming message (agent API, `message_type:
incoming`) and STOPS — it does NOT also call our webhook directly. Chatwoot's
own webhook does that automatically, exactly like a real WhatsApp message
would, so the conversation in the Chatwoot UI shows both sides (lead + agent),
not just the agent's replies. (Calling both was tried and is wrong: it races
Chatwoot's own webhook delivery and the second call just reports `duplicate`.)

If the org has no Chatwoot config (or `--skip-chatwoot`), this falls back to
the pure internal-webhook simulation (synthetic message id, no Chatwoot
involved at all) — useful when Chatwoot isn't running. If `--conversation-id`
isn't a real Chatwoot conversation, the script fails fast with a clear error.

The terminal echo below (polling `outbox_events`, §5.2) is only a debug
confirmation; pass `--no-wait` to skip it and rely on Chatwoot alone.

Usage (first turn of a fresh conversation):
    uv run python scripts/send_lead_message.py --new --org-id <ORG_UUID> "Hola! buenas tardes"

Usage (every following turn — org/conversation/phone/name/message-counter are
remembered in .e2e_chat_session.json, next to this repo's root):
    uv run python scripts/send_lead_message.py "Estoy buscando un departamento para comprar"

Start a second, independent conversation without losing the first one's
session state:
    uv run python scripts/send_lead_message.py --new --conversation-id CW-DEMO-002 \
        "Hola, quiero hablar con un asesor"

Deliver to a real Chatwoot conversation instead of only echoing in the
terminal (requires OrganizationConfig.chatwoot configured, §5.1, and a
conversation already created in the Chatwoot UI):
    uv run python scripts/send_lead_message.py --new --org-id <ORG_UUID> \
        --conversation-id <CHATWOOT_CONVERSATION_ID> --no-wait "Hola! buenas tardes"

Flags:
    --new                start a fresh conversation (new chatwoot_conversation_id
                          unless --conversation-id is given, message counter reset)
    --org-id UUID         organization id (required on the very first call ever)
    --conversation-id     chatwoot conversation id (default: auto-generated on --new —
                          only usable if the org has no Chatwoot config; with Chatwoot
                          configured this MUST be a real conversation id)
    --phone               sender phone / contact_reference (default: +51999888777)
    --name                sender display name (default: "Lead Demo")
    --base-url            webhook host (default: http://localhost:8000)
    --chatwoot-base-url   Chatwoot host AS REACHABLE FROM WHERE THIS SCRIPT RUNS
                          (default: http://localhost:3000) — usually different from
                          the docker-internal base_url stored in OrganizationConfig
    --skip-chatwoot       don't post the lead's message to Chatwoot even if the org
                          has it configured (internal-webhook-only simulation)
    --no-wait             send and return immediately, skip polling for the reply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

import httpx
from sqlalchemy import text

_STATE_PATH = Path(__file__).resolve().parent.parent / ".e2e_chat_session.json"
_DEFAULT_BASE_URL = "http://localhost:8000"
_DEFAULT_CHATWOOT_BASE_URL = "http://localhost:3000"
_DEFAULT_PHONE = "+51999888777"
_DEFAULT_NAME = "Lead Demo"
_POLL_TIMEOUT_SECONDS = 20.0
_POLL_INTERVAL_SECONDS = 0.5


def _load_state() -> dict:
    if _STATE_PATH.exists():
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_state(state: dict) -> None:
    _STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("text", help="Free-text lead message to send")
    parser.add_argument("--new", action="store_true", help="Start a fresh conversation")
    parser.add_argument("--org-id", dest="org_id", help="Organization UUID")
    parser.add_argument(
        "--conversation-id", dest="conversation_id", help="Chatwoot conversation id"
    )
    parser.add_argument("--phone", help="Sender phone (contact_reference)")
    parser.add_argument("--name", help="Sender display name")
    parser.add_argument("--base-url", dest="base_url", help="Webhook base URL")
    parser.add_argument(
        "--chatwoot-base-url",
        dest="chatwoot_base_url",
        help="Chatwoot host as reachable from where this script runs",
    )
    parser.add_argument(
        "--skip-chatwoot",
        action="store_true",
        help="Don't post the lead's message to Chatwoot even if configured",
    )
    parser.add_argument("--no-wait", action="store_true", help="Don't poll for the agent's reply")
    return parser.parse_args()


async def _fetch_chatwoot_config(org_id: str) -> dict | None:
    """Reads OrganizationConfig.chatwoot straight from the DB — account_id and
    api_access_token, the two fields needed to post a message via the agent API."""
    from app.core.database import get_session_factory

    async with get_session_factory()() as session:
        result = await session.execute(
            text("SELECT chatwoot_config FROM organization_configs WHERE organization_id = :org_id"),
            {"org_id": str(uuid.UUID(org_id))},
        )
        row = result.first()
        return row.chatwoot_config if row is not None else None


async def _post_incoming_to_chatwoot(
    chatwoot_base_url: str, account_id: str, api_access_token: str, conversation_id: str, content: str
) -> str:
    """Posts the lead's message into Chatwoot as an incoming message (agent API,
    message_type=incoming) so it shows up as sent by the contact, not the agent.
    Returns the Chatwoot message id, to reuse as the webhook's message id — the
    same id a real Chatwoot-originated webhook would carry."""
    url = (
        f"{chatwoot_base_url.rstrip('/')}/api/v1/accounts/{account_id}"
        f"/conversations/{conversation_id}/messages"
    )
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            url,
            json={"content": content, "message_type": "incoming"},
            headers={"api_access_token": api_access_token},
        )
    if response.status_code == 404:
        raise SystemExit(
            f"Chatwoot devolvió 404 para la conversación '{conversation_id}' en "
            f"{chatwoot_base_url} — no es una conversación real. Créala en la UI de "
            "Chatwoot y usa su id numérico en --conversation-id (ver §5.1 del checklist)."
        )
    response.raise_for_status()
    return str(response.json()["id"])


async def main() -> None:
    args = _parse_args()
    state = _load_state()

    org_id = args.org_id or state.get("org_id")
    if not org_id:
        raise SystemExit(
            "Falta --org-id (no hay sesión previa en .e2e_chat_session.json). "
            "Pásalo una vez: --new --org-id <UUID>."
        )

    if args.new:
        conversation_id = args.conversation_id or f"CW-DEMO-{int(time.time())}"
        seq = 0
    else:
        conversation_id = args.conversation_id or state.get("conversation_id")
        seq = state.get("seq", 0)
        if not conversation_id:
            raise SystemExit("No hay conversación activa — arranca una con --new.")

    phone = args.phone or state.get("phone") or _DEFAULT_PHONE
    name = args.name or state.get("name") or _DEFAULT_NAME
    base_url = args.base_url or state.get("base_url") or _DEFAULT_BASE_URL
    chatwoot_base_url = (
        args.chatwoot_base_url or state.get("chatwoot_base_url") or _DEFAULT_CHATWOOT_BASE_URL
    )

    seq += 1
    sent_at = time.time()
    print(f"→ [{conversation_id}] {args.text}")

    delivered_via_chatwoot = False
    if not args.skip_chatwoot:
        chatwoot_config = await _fetch_chatwoot_config(org_id)
        if chatwoot_config is None:
            print("  (org sin OrganizationConfig.chatwoot — se simula el webhook interno, §5.2)")
        else:
            message_id = await _post_incoming_to_chatwoot(
                chatwoot_base_url,
                chatwoot_config["account_id"],
                chatwoot_config["api_access_token"],
                conversation_id,
                args.text,
            )
            print(
                f"  chatwoot: mensaje entrante #{message_id} creado en conversación "
                f"{conversation_id} — el webhook de Chatwoot (account webhook, §5.1) "
                "lo va a reenviar solo, no se llama nuestro webhook a mano."
            )
            delivered_via_chatwoot = True

    if not delivered_via_chatwoot:
        message_id = f"MSG-{seq:04d}"
        payload = {
            "event": "message_created",
            "message_type": "incoming",
            "private": False,
            "id": message_id,
            "content": args.text,
            "created_at": int(sent_at),
            "sender": {"name": name, "phone_number": phone},
            "conversation": {"id": conversation_id, "channel": "Channel::Whatsapp"},
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{base_url}/api/v1/webhooks/chatwoot/{org_id}", json=payload
            )
        response.raise_for_status()
        print(f"  webhook: {response.status_code} {response.json()}")

    _save_state(
        {
            "org_id": org_id,
            "conversation_id": conversation_id,
            "phone": phone,
            "name": name,
            "base_url": base_url,
            "chatwoot_base_url": chatwoot_base_url,
            "seq": seq,
        }
    )

    if args.no_wait:
        return

    reply = await _wait_for_reply(org_id, conversation_id, sent_at)
    if reply is None:
        print(
            f"  (sin respuesta en {_POLL_TIMEOUT_SECONDS:.0f}s — revisa que "
            "`uvicorn app.main:app` esté corriendo, o consulta outbox_events a mano, §5)"
        )
    else:
        print(f"← {reply}")


async def _wait_for_reply(org_id: str, conversation_id: str, sent_at: float) -> str | None:
    from app.core.database import get_session_factory

    deadline = time.monotonic() + _POLL_TIMEOUT_SECONDS
    async with get_session_factory()() as session:
        while time.monotonic() < deadline:
            result = await session.execute(
                text(
                    "SELECT payload -> 'fields' ->> 'response' AS response "
                    "FROM outbox_events "
                    "WHERE event_type = 'ResponseReady' "
                    "  AND organization_id = :org_id "
                    "  AND payload -> 'fields' ->> 'chatwoot_conversation_id' = :conversation_id "
                    "  AND occurred_at >= to_timestamp(:sent_at) "
                    "ORDER BY occurred_at ASC "
                    "LIMIT 1"
                ),
                {
                    "org_id": str(uuid.UUID(org_id)),
                    "conversation_id": conversation_id,
                    "sent_at": sent_at - 1,  # small slack for clock skew
                },
            )
            row = result.first()
            if row is not None and row.response:
                return row.response
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
    return None


if __name__ == "__main__":
    # Windows consoles (cmd/PowerShell) default to a non-UTF-8 codepage;
    # without this, the accented characters above (as seen in --help output)
    # mangle into mojibake.
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")

    try:
        asyncio.run(main())
    except httpx.HTTPStatusError as exc:
        print(f"Webhook error: {exc.response.status_code} {exc.response.text}", file=sys.stderr)
        raise SystemExit(1) from exc
