"""One-shot seeding for the manual E2E test (docs/e2e-manual-chat-checklist.md
§4): upserts the demo property catalog for ONE organization and computes real
Gemini embeddings (gemini-embedding-001, 1536 dims) through the repo's own
ingestion primitives, so `source_hash` semantics match production ingestion
and re-runs are idempotent (unchanged content never re-embeds).

Usage:
    uv run python scripts/seed_recommendation_demo.py [ORG_NAME_FILTER]

ORG_NAME_FILTER defaults to "demo" and must match exactly one organization by
case-insensitive substring. Aborts when GEMINI_API_KEY is missing — the
`vector(1536)` column cannot store the 16-dim hash fallback (checklist G3).
"""

from __future__ import annotations

import asyncio
import sys
import uuid

import truststore
from sqlalchemy import select, text

# Same OS-truststore injection as app/main.py: without it the OpenAI
# embeddings call fails with CERTIFICATE_VERIFY_FAILED behind AV/corporate
# TLS interception.
truststore.inject_into_ssl()

from app.core.config import get_settings
from app.modules.lead_qualification.domain.models import PropertyType
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.modules.recommendation.application.property_ingestion import (
    HashEmbeddingModel,
    content_hash,
)
from app.modules.recommendation.domain.models import Property, PropertyEmbedding
from app.modules.recommendation.infrastructure.embedding_model import build_embedding_model
from app.modules.recommendation.infrastructure.repository import PropertyRepository
from app.shared.domain.base import utcnow

#: Fixed namespace => stable property ids per (org, external_id): re-running
#: the script upserts the same rows instead of duplicating (same convention as
#: MockInventorySource).
_NAMESPACE = uuid.UUID("4b5f0c72-91d3-4e0a-8f21-7a6e5d3c2b1a")

#: (external_id, price, zone, type, features, description, name_address, links)
#: Zones = Lima districts from qualification's _KNOWN_ZONES (checklist G7);
#: prices aligned to the E2E script budget 200k-300k, with SEED-005/006 as
#: negative controls (over budget / off-zone). `links` son URLs reales de
#: proyectos/brochures (sin parámetros de tracking) para
#: `Property.link_references` — metadata que NO entra al content_hash, así
#: que agregarlas/cambiarlas no fuerza re-embedding.
_CATALOG: tuple[
    tuple[str, float, str, PropertyType, tuple[str, ...], str, str, tuple[str, ...]], ...
] = (
    (
        "SEED-001", 245000.0, "Miraflores", PropertyType.APARTMENT,
        ("cochera", "balcon", "ascensor", "pet_friendly"),
        "Departamento de 2 dormitorios cerca del malecón, cocina remodelada, edificio con ascensor.",
        "Av. Larco 1301, Miraflores",
        ("https://edifica.com.pe/uploads/studio-4-brochure.pdf",),
    ),
    (
        "SEED-002", 289000.0, "Miraflores", PropertyType.APARTMENT,
        ("cochera", "balcon", "gimnasio", "terraza"),
        "Departamento moderno de 3 dormitorios con terraza y vista a parque, incluye cochera doble.",
        "Calle Alcanfores 455, Miraflores",
        ("https://quatroinmobiliaria.pe/d4shb04rd-quatro/upload/2019/09/brochere-living-tower.pdf",),
    ),
    (
        "SEED-003", 275000.0, "San Isidro", PropertyType.APARTMENT,
        ("cochera", "balcon", "seguridad_24h"),
        "Flat de estreno en el corazón financiero, 2 dormitorios, balcón amplio y cochera.",
        "Av. Javier Prado Oeste 980, San Isidro",
        ("https://taleinmobiliaria.com/departamentos-venta/san-isidro-santo-toribio-435/",),
    ),
    (
        "SEED-004", 210000.0, "Surco", PropertyType.APARTMENT,
        ("balcon", "areas_comunes"),
        "Departamento de 2 dormitorios frente a parque, condominio con áreas comunes. Sin cochera.",
        "Av. Caminos del Inca 2200, Surco",
        (
            "https://abril.pe/departamentos/lince/"
            "orquidea-departamentos-en-venta-en-lince-abril-grupo-inmobilario/",
        ),
    ),
    (
        "SEED-005", 450000.0, "San Isidro", PropertyType.HOUSE,
        ("cochera", "jardin", "estudio"),
        "Casa de 4 dormitorios con jardín interior, zona residencial tranquila.",
        "Calle Los Nogales 120, San Isidro",
        ("https://evergran.pe/proyectos/la-Marina-3420",),
    ),
    (
        "SEED-006", 165000.0, "Chorrillos", PropertyType.APARTMENT,
        ("balcon",),
        "Departamento de 1 dormitorio con vista al mar, edificio frente al malecón.",
        "Malecón Grau 300, Chorrillos",
        ("https://www.viva.com.pe/proyecto/parques-del-mar",),
    ),
)


async def main(name_filter: str) -> None:
    settings = get_settings()
    embedder = build_embedding_model(settings.gemini_api_key)
    if isinstance(embedder, HashEmbeddingModel):
        raise SystemExit(
            "GEMINI_API_KEY no está en .env — abortando: vector(1536) no puede "
            "almacenar los vectores hash de 16 dims (checklist G3)."
        )

    from app.core.database import get_session_factory

    async with get_session_factory()() as session:
        organizations = (await session.execute(select(OrganizationORM))).scalars().all()
        matches = [o for o in organizations if name_filter.lower() in o.name.lower()]
        if len(matches) != 1:
            listing = ", ".join(f"{o.id}={o.name!r}" for o in organizations) or "(ninguna)"
            raise SystemExit(
                f"Se esperaba exactamente 1 organización que contenga {name_filter!r}; "
                f"encontradas: {listing}"
            )
        org = matches[0]
        print(f"Organización: {org.name} ({org.id})")

        repo = PropertyRepository(session)
        now = utcnow()
        catalog_props: list[Property] = []
        for external_id, price, zone, ptype, features, description, address, links in _CATALOG:
            prop = Property(
                id=uuid.uuid5(_NAMESPACE, f"{org.id}:{external_id}"),
                organization_id=org.id,
                external_id=external_id,
                price=price,
                zone=zone,
                property_type=ptype,
                features=features,
                description=description,
                name_address=address,
                link_references=links,
                estado="disponible",
                updated_at=now,
            )
            await repo.upsert(prop)
            catalog_props.append(prop)

        # Commit the catalog (incl. link_references) BEFORE embeddings: an
        # OpenAI failure (quota, network) must not roll back the upserts, and
        # the idempotent re-run then only embeds what is still missing.
        await session.commit()
        print(f"Catálogo: {len(catalog_props)} propiedades upserted.")

        embedded = 0
        for prop in catalog_props:
            new_hash = content_hash(prop)
            if await repo.get_embedding_hash(prop.id) == new_hash:
                print(f"  {prop.external_id}: sin cambios (embedding vigente)")
                continue
            vector = await embedder.embed(prop)
            await repo.save_embedding(
                PropertyEmbedding(
                    property_id=prop.id,
                    vector=vector,
                    model_version=embedder.model_version,
                    computed_at=now,
                ),
                source_hash=new_hash,
            )
            await session.commit()
            embedded += 1
            print(f"  {prop.external_id}: embedding actualizado ({len(vector)} dims)")

        verification = await session.execute(
            text(
                "SELECT p.external_id, p.district, p.price, "
                "p.link_references ->> 0 AS link, vector_dims(e.vector) AS dims "
                "FROM properties p "
                "LEFT JOIN property_embeddings e ON e.property_id = p.id "
                "WHERE p.organization_id = :org_id AND p.external_id LIKE 'SEED-%' "
                "ORDER BY p.external_id"
            ),
            {"org_id": str(org.id)},
        )
        print("\nVerificación en base:")
        for row in verification:
            print(
                f"  {row.external_id} | {row.district} | {row.price:,.0f} "
                f"| dims={row.dims} | {row.link}"
            )
        print(f"\nListo: {embedded} embeddings computados/actualizados.")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "demo"))
