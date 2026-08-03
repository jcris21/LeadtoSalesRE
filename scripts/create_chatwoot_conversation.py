"""Crea una conversación nueva en Chatwoot vía API (sin usar la UI) y la deja
lista para usarse como --conversation-id de scripts/send_lead_message.py.

Útil cuando la UI de Chatwoot no permite crear conversaciones manualmente
(inboxes que solo aceptan conversaciones "de afuera", vía canal) — este script
las crea igual, hablando directo con la API de Chatwoot (agent API), igual que
hace ChatwootClient para enviar mensajes salientes.

Pasos que hace:
1. Lee el ORG_ID (arg o .e2e_chat_session.json) y busca su
   OrganizationConfig.chatwoot en la DB (account_id, inbox_id, api_access_token,
   base_url) — igual que send_lead_message.py.
2. Busca un contacto en Chatwoot con el teléfono dado; si no existe, lo crea
   (esto genera también el contact_inbox / source_id que la conversación
   necesita).
3. Crea la conversación (POST .../conversations) contra ese inbox y contacto.
4. Imprime el id numérico de la conversación y actualiza
   .e2e_chat_session.json (conversation_id nuevo, seq reseteado a 0) para que
   el próximo `send_lead_message.py` (sin --new) continúe ahí mismo.

Uso:
    uv run python scripts/create_chatwoot_conversation.py --org-id <ORG_UUID>
    uv run python scripts/create_chatwoot_conversation.py   # reusa org_id de la sesión

Flags:
    --org-id              organization id (default: el de .e2e_chat_session.json)
    --phone               teléfono del contacto (default: +51999888777)
    --name                nombre del contacto (default: Lead Demo)
    --chatwoot-base-url   host de Chatwoot alcanzable desde donde corre este
                          script (default: http://localhost:3000)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx
from sqlalchemy import text

_STATE_PATH = Path(__file__).resolve().parent.parent / ".e2e_chat_session.json"
_DEFAULT_CHATWOOT_BASE_URL = "http://localhost:3000"
_DEFAULT_PHONE = "+51999888777"
_DEFAULT_NAME = "Lead Demo"


def _load_state() -> dict:
    if _STATE_PATH.exists():
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_state(state: dict) -> None:
    _STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--org-id", dest="org_id", help="Organization UUID")
    parser.add_argument("--phone", help="Teléfono del contacto (contact_reference)")
    parser.add_argument("--name", help="Nombre del contacto")
    parser.add_argument(
        "--chatwoot-base-url",
        dest="chatwoot_base_url",
        help="Chatwoot host como lo alcanza este script",
    )
    return parser.parse_args()


async def _fetch_chatwoot_config(org_id: str) -> dict | None:
    from app.core.database import get_session_factory

    async with get_session_factory()() as session:
        result = await session.execute(
            text("SELECT chatwoot_config FROM organization_configs WHERE organization_id = :org_id"),
            {"org_id": str(uuid.UUID(org_id))},
        )
        row = result.first()
        return row.chatwoot_config if row is not None else None


async def _find_or_create_contact(
    client: httpx.AsyncClient, base_url: str, account_id: str, inbox_id: str, phone: str, name: str
) -> tuple[str, str]:
    """Devuelve (contact_id, source_id) — crea el contacto si no existe."""
    search_url = f"{base_url.rstrip('/')}/api/v1/accounts/{account_id}/contacts/search"
    response = await client.get(search_url, params={"q": phone})
    response.raise_for_status()
    payload = response.json().get("payload", [])
    for contact in payload:
        if contact.get("phone_number") == phone:
            contact_id = str(contact["id"])
            source_id = await _ensure_contact_inbox(client, base_url, account_id, inbox_id, contact_id)
            return contact_id, source_id

    create_url = f"{base_url.rstrip('/')}/api/v1/accounts/{account_id}/contacts"
    response = await client.post(
        create_url,
        json={"inbox_id": inbox_id, "name": name, "phone_number": phone},
    )
    response.raise_for_status()
    body = response.json()
    contact_id = str(body["payload"]["contact"]["id"])
    source_id = body["payload"]["contact_inbox"]["source_id"]
    return contact_id, source_id


async def _ensure_contact_inbox(
    client: httpx.AsyncClient, base_url: str, account_id: str, inbox_id: str, contact_id: str
) -> str:
    url = f"{base_url.rstrip('/')}/api/v1/accounts/{account_id}/contacts/{contact_id}/contact_inboxes"
    response = await client.post(url, json={"inbox_id": inbox_id})
    response.raise_for_status()
    return response.json()["source_id"]


async def _create_conversation(
    client: httpx.AsyncClient, base_url: str, account_id: str, inbox_id: str, contact_id: str, source_id: str
) -> str:
    url = f"{base_url.rstrip('/')}/api/v1/accounts/{account_id}/conversations"
    response = await client.post(
        url,
        json={
            "source_id": source_id,
            "inbox_id": inbox_id,
            "contact_id": contact_id,
            "status": "open",
        },
    )
    response.raise_for_status()
    return str(response.json()["id"])


async def main() -> None:
    args = _parse_args()
    state = _load_state()

    org_id = args.org_id or state.get("org_id")
    if not org_id:
        raise SystemExit("Falta --org-id (no hay sesión previa en .e2e_chat_session.json).")

    phone = args.phone or state.get("phone") or _DEFAULT_PHONE
    name = args.name or state.get("name") or _DEFAULT_NAME
    chatwoot_base_url = args.chatwoot_base_url or state.get("chatwoot_base_url") or _DEFAULT_CHATWOOT_BASE_URL

    chatwoot_config = await _fetch_chatwoot_config(org_id)
    if chatwoot_config is None:
        raise SystemExit(
            "La organización no tiene OrganizationConfig.chatwoot configurado — "
            "no se puede crear la conversación vía API (ver §5.1 del checklist)."
        )

    account_id = chatwoot_config["account_id"]
    inbox_id = chatwoot_config["inbox_id"]
    api_access_token = chatwoot_config["api_access_token"]

    async with httpx.AsyncClient(timeout=10.0, headers={"api_access_token": api_access_token}) as client:
        contact_id, source_id = await _find_or_create_contact(
            client, chatwoot_base_url, account_id, inbox_id, phone, name
        )
        conversation_id = await _create_conversation(
            client, chatwoot_base_url, account_id, inbox_id, contact_id, source_id
        )

    print(f"Conversación creada: id={conversation_id} (contact_id={contact_id}, inbox_id={inbox_id})")

    _save_state(
        {
            "org_id": org_id,
            "conversation_id": conversation_id,
            "phone": phone,
            "name": name,
            "base_url": state.get("base_url", "http://localhost:8000"),
            "chatwoot_base_url": chatwoot_base_url,
            "seq": 0,
        }
    )
    print(
        "Guardado en .e2e_chat_session.json — el próximo "
        "`send_lead_message.py` (sin --new) sigue en esta conversación."
    )


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")

    try:
        asyncio.run(main())
    except httpx.HTTPStatusError as exc:
        print(f"Chatwoot API error: {exc.response.status_code} {exc.response.text}", file=sys.stderr)
        raise SystemExit(1) from exc
