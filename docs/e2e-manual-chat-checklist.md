# Checklist — Prueba manual E2E del chat: saludo → recomendación (sin WhatsApp/Meta)

> Objetivo: simular a un lead conversando por el canal WhatsApp **sin** la integración
> Meta, inyectando mensajes directamente en el webhook de Chatwoot del backend, y
> verificar cada respuesta del agente hasta recibir el Top-3 de recomendaciones.
>
> Protocolo acordado: **cada mensaje del guion se envía solo con autorización explícita
> del operador**, y tras cada envío se revisa la respuesta del agente + estado en DB.

---

## 1. Cómo se simula el canal sin Meta

El punto de entrada real del chat es el webhook de Chatwoot — no hay dependencia de Meta
en el backend (`app/modules/conversation_ownership/api/webhook_router.py`):

```
POST /api/v1/webhooks/chatwoot/{organization_id}
```

Payload mínimo que imita un mensaje entrante de WhatsApp (un `curl` por turno del lead):

```bash
curl -s -X POST "http://localhost:8000/api/v1/webhooks/chatwoot/$ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "event": "message_created",
    "message_type": "incoming",
    "private": false,
    "id": "MSG-001",
    "content": "Hola! buenas tardes",
    "created_at": 1752682000,
    "sender": { "name": "Lead Prueba", "phone_number": "+51999888777" },
    "conversation": { "id": "CW-TEST-001", "channel": "Channel::Whatsapp" }
  }'
```

Reglas del payload:
- `id` (mensaje) debe ser **único por turno** (`MSG-001`, `MSG-002`, …) — hay guard de idempotencia.
- `conversation.id` se mantiene **fijo** durante todo el escenario (misma conversación).
- `sender.phone_number` es el `contact_reference` que enlaza la conversación con el Lead (`LeadLinker`).

La respuesta del agente viaja como evento `ResponseReady` por el outbox y se entrega vía
`ChatwootClient.send_message`. **Sin Chatwoot configurado, la respuesta se descarta** —
ver workaround de observación en §5.

---

## 2. ⚠️ Gaps críticos que faltan cerrar (advertencias)

| # | Gap | Severidad | Impacto en la prueba |
|---|-----|-----------|----------------------|
| G1 | ✅ **CERRADO (2026-07-17).** El Coordinator ahora ejecuta los extractores sobre cada mensaje del lead (`qualification_turn.py`): keywords determinísticos primero (con guard anti-falso-budget) y, en mismatch, fallback LLM (`generative_extractor.py`, Gemini `gemini-2.5-flash` con la misma `GEMINI_API_KEY`; sin key = solo keywords). Re-prompts de extractores reemplazan la respuesta plantilla; lo extraído queda en el decision trace (`qualification.run_turn`). Cubierto por `tests/test_coordinator_qualification_turn.py` (guion completo → `ProfileCompleted`). | ✅ Resuelto | El guion §6 corre en **modo puro chat** — los endpoints QA quedan solo para regresión del write-path, sin rol en el E2E. |
| G2 | ✅ **CERRADO (2026-07-17).** El wiring inyecta `build_profile_query_embedder(gemini_api_key)`: el BuyerProfile se embebe con el mismo modelo que el corpus (`gemini-embedding-001`, task `RETRIEVAL_QUERY`, 1536 dims normalizados). Además `SemanticRetrievalService` tiene sonda de dimensiones: ante mismatch NO toca el SQL pgvector y cae al ranking in-memory (`tests/test_query_embedding.py`). | ✅ Resuelto | El pipeline de recomendación llega a `semantic_search` con dims compatibles; sin key, degrada al fallback in-memory sin crash. |
| G3 | ✅ **CERRADO (2026-07-17).** `GEMINI_API_KEY` en `.env` y seed ejecutado: `scripts/seed_recommendation_demo.py` dejó las 6 propiedades demo con embeddings reales de 1536 dims (verificado `vector_dims=1536` en las 6). El seed aborta explícitamente si falta la key (el fallback hash de 16 dims no cabe en `vector(1536)`). | ✅ Resuelto | Re-runs son idempotentes (gate por `source_hash`): solo re-embebe lo que cambió. Nota de entorno: la salida TLS pasa por el almacén de certificados del OS (`truststore`, inyectado en `app/main.py` y el seed) — necesario en esta máquina por interceptación TLS del antivirus. |
| G4 | ✅ **CERRADO (2026-07-18).** LLM conversacional conectado detrás de `ConversationBrain` de forma **agnóstica al proveedor**: `LLMConversationBrain` habla con un `ChatModelPort` neutral (`conversation_ownership/infrastructure/llm_brain.py`); el único código provider-aware es el adaptador (`GeminiChatModel`, reusa `GEMINI_API_KEY`, modelo en `CONVERSATION_LLM_MODEL`, default `gemini-2.5-flash`). Sin key o ante fallo del modelo, degrada a `TemplateBrain` (los templates quedan como hook futuro para saludos/keywords por broker). System prompt transversal de prueba en `domain/prompts.py` (fallback; un prompt activo del Prompt Registry por org siempre gana). Medición: cada turno loguea `conversation_brain_turn source=llm\|template_fallback model=... latency_ms=... history_turns=...` y la respuesta queda en el decision trace. Cubierto por `tests/test_llm_conversation_brain.py`. | ✅ Resuelto | La prueba ahora valida pipeline **y** inteligencia conversacional: latencia/fallback-rate desde logs, calidad desde el decision trace. |
| G5 | **Entrega de respuesta exige `OrganizationConfig.chatwoot`.** Sin config, `handle_response_ready` descarta el mensaje (solo log de error). | 🟠 Alto | Opción A: levantar Chatwoot local (docker-compose) y configurar la org. Opción B (recomendada para esta prueba): leer las respuestas directamente de `outbox_events` (§5). |
| G6 | ✅ **CERRADO para la prueba (2026-07-17).** `properties` y `property_embeddings` ya no están vacías: `scripts/seed_recommendation_demo.py` (§4) siembra el catálogo demo (con `link_references` reales) + embeddings vía las primitivas del repo. Sigue sin haber trigger de ingesta en producción — pendiente para una épica posterior, no bloquea el E2E. | ✅ Resuelto (para E2E) | Re-ejecutable en cualquier momento; idempotente. |
| G7 | ✅ **CERRADO (2026-07-18).** Mismatch de zonas resuelto en ambos lados: los seeds del E2E ya usaban distritos de Lima (§4, `_KNOWN_ZONES`), y ahora `MockInventorySource` también fue realineado a Lima (Palermo→Miraflores, Recoleta→San Isidro, Belgrano→Surco, Villa Crespo→Barranco) con comentario que ancla el catálogo a `_KNOWN_ZONES`. Los tests de ingesta solo dependen del tamaño del catálogo (10), no de las zonas. | ✅ Resuelto | El filtro estructurado por zona nunca devuelve 0 candidatos por mismatch de ciudad, ni con el seed demo ni con el mock de ingesta. |
| G8 | ✅ **CERRADO (2026-07-19).** Los leads ahora nacen desde el chat: mientras la conversación no tiene Lead vinculado, el Coordinator responde pidiendo el nombre (`REPROMPT_IDENTITY`); el primer mensaje con nombre (extractor determinístico `identity_extraction.py`: "me llamo …"/"soy …"/nombre a secas, DNI opcional de 8 dígitos) crea el deal en wacrm (`WacrmClient.create_lead`, stage `New`, teléfono = `contact_reference`) vía `LeadSyncAdapter.create_lead` con **espejo local inmediato** en la misma transacción — sin esperar el poll CDC; el siguiente poll converge idempotente sobre la misma fila. Si ya existe un lead local con ese teléfono se vincula sin duplicar; si wacrm falla, se re-pregunta y se reintenta al siguiente turno. Cubierto por `tests/test_coordinator_identity_gate.py`, `tests/test_identity_extraction.py` y los tests de adapter/cliente. **Addendum 2026-07-19:** el fork real de wacrm no tenía creación de deals por API — se añadió `POST /api/v1/deals` (scope `deals:write`, idempotente por teléfono: reutiliza el deal abierto del contacto) y el `contact_dni` se registra en `deals.notes` (`DNI: XXXXXXXX`), visible en el apartado Notes del deal card. | ✅ Resuelto | El guion ya no requiere pre-crear el lead: el paso inicial del chat es dejar el nombre (mensaje de bienvenida G8) y el lead aparece en `leads` en ese mismo turno. |
| G9 | **Umbral de completitud = 90 %** (`profile_completeness_threshold`), y hay **8 dimensiones** con peso igual (7/8 = 87.5 % < 90). *(2026-07-19: se añadió `bedrooms` — número de habitaciones — como octava dimensión: extractor determinístico "N dormitorios/habitaciones/cuartos/ambientes" + fallback generativo + migración 0015; el conteo entra también al texto del query embedding.)* | 🟡 Medio | El guion debe capturar **las 8 dimensiones** (budget, locations, property_type, timeline, must_haves, financing_type, decision_maker_mode, bedrooms) para disparar `ProfileCompleted`. |
| G10 | Enriquecimiento de barrio (Google Maps) sin API key → siempre `neighborhood=None`. | 🟢 Bajo | Comportamiento esperado y documentado; el mensaje Top-3 sale sin la línea "Cerca de:". |
| G11 | ✅ **CERRADO (2026-07-19, hallado corriendo este guion).** El turno de identidad alimentaba el mismo mensaje a los extractores de calificación: el DNI de 8 dígitos era capturado como budget (`budget_min/max = 45 678 912`). Fix: `_identity_gate` devuelve `(ask_identity, identity_consumed)` y el Coordinator omite `run_qualification_turn` en el turno que consumió nombre/DNI — la calificación empieza en el mensaje siguiente. Test: `test_identity_message_is_not_fed_to_qualification_extractors`. | ✅ Resuelto | El perfil del lead E2E se saneó a mano (budget→NULL); ningún turno posterior re-contaminó. |
| G12 | **Worker de outbox reintenta entregas fallidas sin tope ni backoff** — observados 323 intentos contra una conversación inexistente en Chatwoot (`CW-TEST-001`); solo se detiene marcando `processed_at` a mano. | 🟡 Medio | Ruido de logs y carga constante; una cola de eventos imposibles crece sin límite. Pendiente: `max_attempts` + dead-letter (o descarte con auditoría). |
| G13 | ✅ **CERRADO (2026-07-22).** El checkpointer LangGraph por defecto pasó de `InMemorySaver` a `AsyncPostgresSaver` (`langgraph-checkpoint-postgres`, pool `psycopg` propio — segundo driver Postgres junto al `asyncpg`/SQLAlchemy existente, ya que no hay checkpointer async oficial sobre asyncpg), inicializado en el `lifespan` de `app/main.py`; si falla al iniciar (DB inalcanzable, credenciales) degrada a `InMemorySaver` y loguea el error sin tumbar el boot (`conversation_checkpointer=memory` como palanca de rollback). Además `TurnState.messages` ahora se acota a las últimas `conversation_history_window_turns` (12 por defecto) y los turnos evictados se pliegan en un `summary` determinístico (sin LLM, longitud acotada) que viaja en el mismo checkpoint y se antepone al historial del brain como mensaje `system`. **Nota de infraestructura:** las tablas del checkpoint (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`) las crea `AsyncPostgresSaver.setup()` de forma idempotente en cada boot — **no** hay migración de Alembic para ese esquema (lo versiona la propia librería); `alembic upgrade head` ya no describe el 100% del schema. Test de aceptación real: `test_restart_simulation_new_responder_instance_resumes_shared_checkpoint` (nueva instancia de `LangGraphResponder`, mismo checkpointer/`thread_id`, resume el contexto). | ✅ Resuelto | El perfil no se afecta (vive en DB) y la extracción sigue correcta; ahora tampoco se resetea la UX conversacional tras un restart del proceso. |

**Resumen (actualizado 2026-07-18):** los bloqueantes de código y datos están cerrados —
**G1** (extractores + fallback LLM), **G2** (query embedding Gemini + sonda de dims),
**G3/G6/G7** (seed ejecutado: 6 propiedades Lima con links y embeddings 1536-dim reales;
`MockInventorySource` realineado a distritos de Lima el 2026-07-18),
**G4** (LLM conversacional detrás de `ChatModelPort`, con degradación a templates y
métricas por turno). Para correr el guion falta solo: (a) lead espejado (**G8**) y
(b) decidir el canal de observación de respuestas (**G5**, §5). G10 (sin Maps key) es
la única limitación aceptada de esta prueba.

---

## 3. Checklist de preparación (marcar antes de iniciar el guion)

### Infraestructura
- [x] `.env` con `DATABASE_URL` (Supabase Postgres), `JWT_SECRET` y `GEMINI_API_KEY` — una sola key de Google habilita embeddings (G2/G3) **y** el fallback LLM de extracción (G1, `gemini-2.5-flash`).
- [x] Migraciones al día: `alembic upgrade head` (14 revisiones — incluye pgvector + HNSW y la 0014 `estado` enum→varchar; aplicadas 2026-07-17).
- [ ] App corriendo: `uvicorn app.main:app --port 8000` — el worker de outbox, el decay loop y el `crm_sync_loop` arrancan con el lifespan.
- [ ] wacrm accesible: instancia real local (`:3005`) con CrmConfig de la org, o mock (`mocks/wacrm_mock`, `:8080`).
- [ ] (Opción A de G5) Chatwoot local levantado vía `docker-compose` + `OrganizationConfig.chatwoot` completo (inbox_id, account_id, api_access_token, base_url).

### Datos base
- [ ] Organización creada (tabla `organizations`) — anotar `ORG_ID`.
- [ ] Admin registrado y JWT obtenido (para los endpoints QA de perfil, workaround G1):
      `POST /api/v1/auth/register` → `POST /api/v1/auth/login`.
- [ ] Lead con teléfono `+51999888777` espejado en la tabla `leads` de la app
      (vía wacrm + poll CDC, o INSERT directo) — anotar `LEAD_ID`:
      ```sql
      SELECT id, contact_reference FROM leads
      WHERE organization_id = :org_id AND contact_reference = '+51999888777';
      ```
- [x] Seeds de propiedades + embeddings aplicados (§4, ejecutado 2026-07-17: 6/6 con `vector_dims=1536` y `link_references`) — re-verificar con:
      ```sql
      SELECT p.external_id, p.district, p.price, (e.property_id IS NOT NULL) AS has_embedding
      FROM properties p LEFT JOIN property_embeddings e ON e.property_id = p.id
      WHERE p.organization_id = :org_id;
      ```
- [ ] (Opcional) Prompt activo del coordinator en el Prompt Registry — si falta, usa el fallback y solo genera un WARNING.

### Código (gaps a cerrar antes o durante la prueba)
- [x] **G1**: cerrado — extractores conectados al turno del Coordinator + fallback LLM validado (`qualification_turn.py`, `generative_extractor.py`). El fallback generativo usa Gemini (`gemini-2.5-flash`) con la misma `GEMINI_API_KEY` de embeddings — ya activo.
- [x] **G2**: cerrado — `embed_query` real con Gemini (`build_profile_query_embedder`) inyectado por el wiring + sonda de dimensiones con fallback in-memory en `SemanticRetrievalService`.

---

## 4. Seeds de propiedades para Supabase (pedido #2)

**Camino canónico (ejecutado 2026-07-17):** `uv run python scripts/seed_recommendation_demo.py`
— upserta el catálogo demo (6 propiedades, con `link_references` a proyectos/brochures reales)
y computa embeddings Gemini de 1536 dims con las primitivas del repo (`source_hash` correcto).
Idempotente: re-runs solo re-embeben lo que cambió; el catálogo se commitea antes de los
embeddings, así un fallo de API no pierde los upserts. Requiere `GEMINI_API_KEY` (aborta sin ella).

El SQL siguiente queda **solo como referencia** del contenido sembrado (distritos alineados a
`_KNOWN_ZONES` de Lima, precios alineados al guion 200 000–300 000, columna física de zona =
`district`; los `link_references` reales están en el script, aquí abreviados como `'[]'`):

```sql
-- Reemplazar :org_id por el UUID de la organización.
INSERT INTO properties
  (id, organization_id, external_id, price, district, property_type,
   features, description, name_address, estado, link_references, updated_at)
VALUES
  (gen_random_uuid(), :org_id, 'SEED-001', 245000, 'Miraflores', 'apartment',
   '["cochera","balcon","ascensor","pet_friendly"]',
   'Departamento de 2 dormitorios cerca del malecón, cocina remodelada, edificio con ascensor.',
   'Av. Larco 1301, Miraflores', 'disponible', '[]', now()),
  (gen_random_uuid(), :org_id, 'SEED-002', 289000, 'Miraflores', 'apartment',
   '["cochera","balcon","gimnasio","terraza"]',
   'Departamento moderno de 3 dormitorios con terraza y vista a parque, incluye cochera doble.',
   'Calle Alcanfores 455, Miraflores', 'disponible', '[]', now()),
  (gen_random_uuid(), :org_id, 'SEED-003', 275000, 'San Isidro', 'apartment',
   '["cochera","balcon","seguridad_24h"]',
   'Flat de estreno en el corazón financiero, 2 dormitorios, balcón amplio y cochera.',
   'Av. Javier Prado Oeste 980, San Isidro', 'disponible', '[]', now()),
  (gen_random_uuid(), :org_id, 'SEED-004', 210000, 'Surco', 'apartment',
   '["balcon","areas_comunes"]',
   'Departamento de 2 dormitorios frente a parque, condominio con áreas comunes. Sin cochera.',
   'Av. Caminos del Inca 2200, Surco', 'disponible', '[]', now()),
  (gen_random_uuid(), :org_id, 'SEED-005', 450000, 'San Isidro', 'house',
   '["cochera","jardin","estudio"]',
   'Casa de 4 dormitorios con jardín interior — fuera del presupuesto del guion (control negativo).',
   'Calle Los Nogales 120, San Isidro', 'disponible', '[]', now()),
  (gen_random_uuid(), :org_id, 'SEED-006', 165000, 'Chorrillos', 'apartment',
   '["balcon"]',
   'Departamento de 1 dormitorio con vista al mar — zona fuera del guion (control negativo).',
   'Malecón Grau 300, Chorrillos', 'disponible', '[]', now());
```

**Embeddings (obligatorios — sin fila en `property_embeddings` la propiedad queda
excluida del ranking semántico por el INNER JOIN):**

- **Con `GEMINI_API_KEY` (camino canónico, ya ejecutado):** `scripts/seed_recommendation_demo.py`
  hace catálogo + embeddings en un solo paso (ver arriba) — el one-shot `seed_embeddings_once.py`
  que proponía una versión anterior de este doc quedó superado y no debe crearse.
  Detalle de implementación que importa: en Postgres `PropertyRepository.save_embedding` upserta
  con `CAST(:vec AS vector)` (el bind ORM JSON no es compatible con la columna `vector(1536)`).

- **Sin key (solo para destrabar la prueba):** sembrar vectores dummy de 1536 dims por SQL
  (similitud sin significado; el orden final lo corrige el `WeightedRankingEngine`):

  ```sql
  INSERT INTO property_embeddings (property_id, vector, model_version, source_hash, computed_at)
  SELECT p.id,
         (SELECT ('[' || string_agg(((random()*2)-1)::text, ',') || ']')
            FROM generate_series(1,1536))::vector,
         'seed-dummy-v1', 'seed-' || p.external_id, now()
  FROM properties p
  WHERE p.organization_id = :org_id
    AND NOT EXISTS (SELECT 1 FROM property_embeddings e WHERE e.property_id = p.id);
  ```

---

## 5. Cómo observar la respuesta del agente (sin Chatwoot)

Cada respuesta (conversacional o Top-3) queda como evento `ResponseReady` en el outbox:

```sql
SELECT event_type,
       payload->'fields'->>'response' AS respuesta,
       created_at
FROM outbox_events
WHERE event_type = 'ResponseReady'
ORDER BY created_at DESC
LIMIT 5;
```

> Nota: el worker consume la fila y `handle_response_ready` intentará enviarla a
> Chatwoot; sin config solo se loguea `Organization … has no Chatwoot config`. La
> consulta anterior es el visor oficial de esta prueba. Si el worker marca/borra filas
> procesadas, consultar también los logs de la app.

Estado de la conversación y del perfil en cualquier momento:

```sql
SELECT state, lead_id, contact_reference FROM conversations
WHERE chatwoot_conversation_id = 'CW-TEST-001';

SELECT * FROM buyer_profiles WHERE lead_id = :lead_id;

SELECT rank, explanation, delivered_at FROM recommendations
WHERE lead_id = :lead_id ORDER BY generated_at DESC, rank;
```

---

## 6. Guion de mensajes del lead (pedido #1) — enviar UNO por vez, con autorización

### Escenario A — Happy path: saludo → 7 dimensiones → Top-3 (modo puro chat, G1 cerrado)

Cada paso indica: mensaje a inyectar (`content` del curl de §1), qué extrae el
Coordinator por sí mismo, y la verificación en DB. **No se usa ningún endpoint**: la
extracción sale del propio mensaje (keywords determinísticos; fallback LLM si hay
`GEMINI_API_KEY` y el keyword no matchea). Este guion exacto está automatizado en
`tests/test_coordinator_qualification_turn.py::test_e2e_script_fills_profile_and_fires_profile_completed`.

| Paso | Mensaje del lead | Extracción esperada | Verificación |
|------|------------------|---------------------|--------------|
| A1 | `Hola! buenas tardes` | — (saludo, sin señal) | Conversación creada, FSM `new → ai_owned → qualification`; respuesta plantilla en `outbox_events`; trace `qualification.run_turn = no_signal`. |
| A2 | `Estoy buscando un departamento para comprar` | `property_type=apartment` | `buyer_profiles.property_type`; completitud ≈ 12.5 %. |
| A2b | `Que tenga 2 dormitorios por favor` | `bedrooms=2` (8.ª dimensión, 2026-07-19; el "2" requiere keyword adyacente — nunca toca budget/timeline) | `buyer_profiles.bedrooms`; ≈ 25 %. |
| A3 | `Me interesa la zona de Miraflores o San Isidro` | `locations=[Miraflores, San Isidro]` | 2 distritos; ≈ 37.5 %. |
| A4 | `Mi presupuesto es de 200 mil a 300 mil dolares` | `budget=200000–300000` | `budget_min/max`; ≈ 50 %. |
| A5 | `Quisiera mudarme en 3 meses como maximo` | `timeline=3_months` (el "3" NO debe tocar budget — guard) | ≈ 62.5 %; budget sigue 200000–300000. |
| A6 | `Es indispensable que tenga cochera y balcon` | `must_haves=[cochera, balcon]` | ≈ 75 %. |
| A7 | `Ya tengo un credito hipotecario aprobado en el banco` | `financing_type=mortgage_approved` | ≈ 87.5 % — **aún < 90 %, no dispara**. |
| A8 | `La decision la tomo junto con mi esposa` | `decision_maker_mode=couple` | 100 % → **`ProfileCompleted`** → pipeline de recomendación → `ResponseReady` con "¡Encontré estas opciones para vos!" y Top-3 (esperado: SEED-002/003/001 dentro de presupuesto y zona; SEED-004 sin cochera puntúa menos; SEED-005/006 filtradas). Verificar `recommendations` con `delivered_at` estampado. |

> Variante free-text (solo con `GEMINI_API_KEY`): reemplazar A2 por algo sin
> keywords, p. ej. `algo chico para vivir cerca del mar` — el fallback LLM debe
> reconocer/clasificar la dimensión o devolver null si el mensaje no corresponde al
> dato pendiente (trace `via:generative`).

### Escenario B — Guardrail bypass (transferencia a humano)

| Paso | Mensaje | Esperado |
|------|---------|----------|
| B1 | `Hola, quiero hablar con un asesor por favor` | **Sin respuesta conversacional**; FSM → `assigned_human`; fila en `ownership_decisions` (bypass). Usar `conversation.id` nueva (`CW-TEST-002`). |
| B2 (variante) | `¿Está la señora María?` | Bypass con `broker_requested="María"`. |

### Escenario C — Objeción (US-209, re-score del lead)

| Paso | Mensaje | Esperado |
|------|---------|----------|
| C1 | `Me parece muy caro, se me va del presupuesto` | Objeción `precio` registrada (`lead_objections`), `lead_score`/`lead_classification` recalculados. Con G1 abierto: ejercitar vía `extract_objection`. |

### Escenario D — Sin inventario que calce (mensaje de vacío)

| Paso | Setup | Esperado |
|------|-------|----------|
| D1 | Repetir A2–A8 con presupuesto `50 mil a 80 mil` (ninguna propiedad sembrada calza) | `ResponseReady` = "No encontré propiedades que coincidan con tu búsqueda por ahora…" y **cero** filas nuevas en `recommendations`. |

---

## 7. Criterios de éxito del E2E

- [x] A1 devuelve el gate de identidad (G8) y la conversación queda en `Qualification` *(2026-07-19, conversación real Chatwoot #2)*.
- [x] Las **8** dimensiones quedan persistidas en `buyer_profiles` (completitud 100 %) *(2026-07-19; incluye `bedrooms=2`)*.
- [x] `ProfileCompleted` aparece en `outbox_events` (completeness 100.0) y es consumido sin errores.
- [x] `recommendations` tiene 3 filas rankeadas con `delivered_at`: SEED-001 Miraflores 245k (el único de 2 dormitorios → rank 1), SEED-003 San Isidro 275k, SEED-002 Miraflores 289k. SEED-004 (sin cochera) fuera del Top-3; SEED-005/006 filtradas.
- [x] El mensaje Top-3 llegó a la UI de Chatwoot. ✅ **CERRADO (2026-07-20).** El signal `type_match` ya está traducido en `explanation_generator.py` (`_SIGNAL_PHRASES`). `_format_recommendation_message` (`recommendation/wiring.py`) ahora agrega dirección/zona/precio y `Enlaces:` (`property.link_references`) por cada propiedad, más un párrafo narrativo LLM (`llm_narrator.py`) que cierra preguntando cuál opción prefiere. Verificado re-disparando `handle_profile_completed` para el lead de este guion y confirmando en la API de Chatwoot (conversación `#2`, mensajes #42/#43) que el Top-3 entregado trae dirección + precio + link por propiedad — comparado contra el mensaje #41 (la corrida original, sin esos datos).
- [ ] B1 transfiere a humano sin generar respuesta; C1 degrada el score; D1 responde el mensaje de vacío. *(Pendientes — escenarios B/C/D.)*
- [x] Push a wacrm del stage calificado: deal `82ada42e…` en **`Qualified`** en el wacrm real *(verificado por API `GET /deals/{id}`)*.
