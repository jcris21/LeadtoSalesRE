# Historias de Usuario — Qualification & Recommendation

Fuente: `Backlog.md` (Epic 2 US-201, Epic 3 US-301), `Maquina_Estados.md`, `Agentic_System.md`,
`Customer_Journey_Residencial_WhatsApp_Detallado.md`, `AI_Recommendation_Domain_Model.md`, código en
`app/modules/lead_qualification/` y `app/modules/recommendation/`.

## Contexto y alcance

El objetivo es centrarse en las épicas **Calificación del Lead** y **Recomendación**, descomponiéndolas
en Historias de Usuario (criterio INVEST, breves) alineadas de forma cohesionada con: capas funcionales,
capa agentic, persistencia de tablas, estados (FSM) y arquitectura esperada.

Se investigó (3 agentes Explore en paralelo + 1 agente de síntesis):

- **Backlog.md**: Epic 2 (US-201, Qualification/Discovery) y Epic 3 (US-301, Recommendation Engine) son
  cajas únicas en formato Gherkin, sin subtareas — el backlog no descompone el pipeline real.
- **Maquina_Estados.md**: Conversation FSM real = New → Greeting → Discovery → Recommendation →
  Scheduling → Waiting Response → Follow-up → Handoff. Evento "Información suficiente" dispara
  Discovery→Recommendation.
- **Customer_Journey...md**: Discovery se hace en 6 bloques de preguntas (perfil familiar, ubicación,
  presupuesto, financiamiento, horizonte, decisión); Recommendation es la sección "Matching" (comparar
  contra inventario, 3 resultados posibles, enviar fotos/plano/video).
- **Agentic_System.md**: arquitectura híbrida SAS (Coordinator Agent + Intent Router + Qualification Flow
  + Objection Handler + Guardrails, todo LLM) + servicios deterministas fuera del SAS (Matching Engine
  con SQL filters + pgvector, Availability Validator, Scheduling Service, Ownership Policy Engine). Nada
  de esto tiene código todavía salvo las guardas deterministas de calificación.
- **Código real** (`app/modules/lead_qualification/`, `app/modules/recommendation/`): ya implementa
  `BuyerProfile`/`PROFILE_DIMENSIONS` (5, no las 6 del journey)/`CompletenessGate`/`StalenessGuard`/
  `LeadSyncAdapter` para Qualification; y el pipeline completo `PropertyIngestionService` →
  `StructuredFilterService` → `SemanticRetrievalService` → `WeightedRankingEngine` →
  `ExplanationGenerator` → `NeighborhoodEnrichmentAdapter` para Recommendation — pero con gaps ya
  conocidos: filtro estructurado y retrieval semántico corren en Python (no SQL/pgvector), embeddings son
  un stand-in hash de 16-dim, `RecommendationResult` nunca se persiste, y no existe ningún
  Coordinator/Intent Router/Objection Handler.
- Reutiliza el cruce contra Supabase ya hecho en una tarea previa (tabla `properties` con drift de
  esquema, `property_embeddings.vector` como jsonb en vez de pgvector real, y el gap de la tabla
  `recommendations` — mismo hallazgo, no se re-audita).

**Corrección aplicada:** el método real del pipeline de ingestión es
`PropertyIngestionService.ingest_from_source(organization_id)` (verificado en
`app/modules/recommendation/application/property_ingestion.py:94`), no `pull_and_upsert` — se usa el
nombre correcto en US-302.

### Estructura del documento

1. Nota global de inconsistencia de nombres de estado (Discovery/Recommendation del doc vs
   QUALIFICATION/RECOMMENDATION del código — se declara una sola vez, no se repite por HU).
2. **Epic 2 — Qualification (Discovery)**: US-202 a US-207 (una HU por dimensión de `PROFILE_DIMENSIONS`
   + Completeness Gate + sync a wacrm — todas ya implementadas o parcialmente), más US-208 y US-209
   marcadas `[GAP — no implementado]` (6ta dimensión del journey — financiamiento/decisión —,
   clasificación Hot/Warm/Cold + objeciones).
3. **Epic 3 — Recommendation Engine**: US-302 a US-307 (una HU por etapa real del pipeline: ingestion,
   structured filter, semantic retrieval, ranking, explanation, neighborhood enrichment), más US-308,
   US-309, US-310 marcadas `[GAP]` (embeddings reales, reconciliación de esquema `properties`,
   persistencia de `recommendations`).
4. **AI-104** `[GAP]`: Coordinator Agent + Intent Router LLM-backed (única historia sin equivalente
   determinista, por eso prefijo `AI-10X`).
5. Tabla resumen final (ID | Título | Estado FSM | Capa agentic | Tabla(s) | Implementado hoy).

Cada HU sigue el formato Gherkin del backlog (`Feature:`/`Scenario:` Given/When/Then) + una sub-sección
**Alineación** de 4 líneas: (a) estado FSM, (b) capa agentic (con nota de si ya existe o es solo diseño),
(c) tabla(s) Supabase, (d) clase/servicio real o gap. Las HUs de Recommendation quedaron acotadas
1 HU ≈ 1 pieza de arquitectura verificable en vez de la caja única que trae el backlog, cumpliendo
Small/Testable de INVEST; se documentan también las HUs ya resueltas por código existente (trazabilidad
HU↔código), no solo los gaps.

## Nota global de inconsistencia de nombres de estado

`Maquina_Estados.md` usa nombres en español título ("Discovery", "Recommendation") para la Conversation
FSM. El código real (`conversation_ownership.domain.models.ConversationState`) usa nombres en mayúsculas
("QUALIFICATION", "RECOMMENDATION"). En cada HU de abajo, "Estado FSM" cita el nombre del documento
seguido del nombre real de código entre paréntesis cuando difiere. No se repite esta nota en cada HU.

---

## Epic 2 — Qualification (Discovery)

### US-202 — Capturar dimensión de presupuesto del perfil

Como AI Agent quiero registrar el rango de presupuesto que declara el lead para poder evaluarlo en el
Completeness Gate.

```gherkin
Feature: Captura de presupuesto
Scenario: Lead declara presupuesto
  Given Conversation State = Discovery
  When el lead envía un rango o monto de presupuesto
  Then BuyerProfile.budget se actualiza con un MoneyRange
  And "budget" aparece en captured_dimensions()
```

**Alineación**
- (a) Estado FSM: Discovery (QUALIFICATION) — no transiciona por sí sola.
- (b) Capa agentic: Qualification Flow — `extract_budget` en
  `app/modules/lead_qualification/application/qualification_flow.py` (extracción determinística
  keyword/regex, sin LLM aún) llama a `BuyerProfileCaptureService.update_profile`. Enrutada desde la
  conversación real: `CoordinatorAgent.handle_message` invoca `run_qualification_turn`
  (`qualification_turn.py`) en cada turno con un `Lead` vinculado — no requiere el endpoint de
  soporte `POST /api/v1/leads/{lead_id}/profile/budget` (que sigue disponible para QA/replays) — ver
  `openspec/changes/qualification-flow-us-202-205/` y
  `openspec/specs/lead-qualification/us-202-205-enrichment.md`.
- (c) Tablas: `buyer_profiles`, `leads`.
- (d) Implementado: `BuyerProfile.apply(patch)` en `lead_qualification/domain`; E2E probado en
  `tests/test_coordinator_qualification_turn.py`.

### US-203 — Capturar dimensión de ubicación

Como AI Agent quiero registrar la(s) zona(s) de interés del lead para acotar el inventario relevante.

```gherkin
Feature: Captura de ubicación
Scenario: Lead menciona distrito o zona
  Given Conversation State = Discovery
  When el lead provee uno o más distritos/zonas
  Then BuyerProfile.locations se actualiza con la tupla de zonas
  And "locations" aparece en captured_dimensions()
```

**Alineación**
- (a) Discovery (QUALIFICATION).
- (b) Qualification Flow — `extract_locations` en `qualification_flow.py` (matching contra catálogo
  fijo de zonas conocidas, sin catálogo por-organización — abierto, ver design.md del change
  original). Enrutada desde la conversación real vía `CoordinatorAgent` → `run_qualification_turn`;
  endpoint de soporte `POST /api/v1/leads/{lead_id}/profile/locations` disponible para QA — ver
  `openspec/changes/qualification-flow-us-202-205/`.
- (c) `buyer_profiles`.
- (d) Implementado: `BuyerProfile.locations: tuple[str]`; E2E probado en
  `tests/test_coordinator_qualification_turn.py`.

### US-204 — Capturar dimensión de tipo de propiedad

Como AI Agent quiero registrar el tipo de propiedad buscado para filtrar el inventario correctamente.

```gherkin
Feature: Captura de tipo de propiedad
Scenario: Lead indica tipo de propiedad
  Given Conversation State = Discovery
  When el lead menciona casa, departamento u otro PropertyType
  Then BuyerProfile.property_type se actualiza
  And "property_type" aparece en captured_dimensions()
```

**Alineación**
- (a) Discovery (QUALIFICATION).
- (b) Qualification Flow — `extract_property_type` en `qualification_flow.py` (keyword matching con
  sinónimos en español, sin llamada LLM para el caso común; mensaje con dos tipos captura el primero
  mencionado). Enrutada desde la conversación real vía `CoordinatorAgent` → `run_qualification_turn`;
  endpoint de soporte `POST /api/v1/leads/{lead_id}/profile/property-type` disponible para QA — ver
  `openspec/changes/qualification-flow-us-202-205/`.
- (c) `buyer_profiles`.
- (d) Implementado: `PropertyType` enum + `BuyerProfile.property_type`; E2E probado en
  `tests/test_coordinator_qualification_turn.py`.

### US-205 — Capturar horizonte de decisión y must-haves

Como AI Agent quiero registrar el timeline de compra y los atributos indispensables para priorizar
recomendaciones y detectar urgencia comercial.

```gherkin
Feature: Captura de timeline y must-haves
Scenario: Lead indica urgencia y requisitos indispensables
  Given Conversation State = Discovery
  When el lead expresa un horizonte temporal o un requisito no negociable
  Then BuyerProfile.timeline y/o must_haves se actualizan
  And las dimensiones correspondientes aparecen en captured_dimensions()
```

**Alineación**
- (a) Discovery (QUALIFICATION).
- (b) Qualification Flow — `extract_timeline_and_must_haves` en `qualification_flow.py` (una sola
  `ProfilePatch` puede portar ambas dimensiones sin borrar la otra; `must_haves` deduplica entradas
  textualmente idénticas dentro de un mismo mensaje). Enrutada desde la conversación real vía
  `CoordinatorAgent` → `run_qualification_turn`; endpoints de soporte
  `POST /api/v1/leads/{lead_id}/profile/timeline` y `.../must-haves` disponibles para QA — ver
  `openspec/changes/qualification-flow-us-202-205/`.
- (c) `buyer_profiles`.
- (d) Implementado: `Timeline` enum, `must_haves: tuple[str]`; E2E probado en
  `tests/test_coordinator_qualification_turn.py`.

> **Nota INVEST:** US-202 a US-205 reemplazan la caja única "descubrir necesidades" de US-201 y son
> independientes entre sí (cada una toca una sola dimensión de `PROFILE_DIMENSIONS`). El Customer Journey
> describe 6 bloques (incluye financiamiento y "decisión: solo/pareja/familia") pero el código solo
> modela 5 dimensiones — se deja como gap explícito en US-208.

### US-206 — Activar Completeness Gate al alcanzar el umbral

Como sistema quiero evaluar automáticamente si el perfil cruzó el umbral de completitud para decidir si
el lead avanza a Recommendation.

```gherkin
Feature: Completeness Gate
Scenario: Perfil alcanza el umbral configurado
  Given BuyerProfile con N dimensiones capturadas
  When completeness(profile) >= settings.profile_completeness_threshold
  Then CompletenessGate.can_advance_to_recommendation retorna can_advance = true
  And se publica el evento ProfileCompleted (una sola vez, no en cada refinamiento)
```

**Alineación**
- (a) Evento de salida "Información suficiente" (doc) = evento `ProfileCompleted` (código); transición
  Discovery→Recommendation (QUALIFICATION→RECOMMENDATION). El Completeness Gate está deliberadamente
  FUERA de la FSM (Agentic_System.md §7.8, QA-14), actúa como precondición.
- (b) Capa agentic: Guardrail lógico, no-LLM — YA implementado.
- (c) `buyer_profiles`, `leads` (pipeline_stage), `outbox_events` (ProfileCompleted).
- (d) Implementado: `CompletenessGate.can_advance_to_recommendation`,
  `BuyerProfileCaptureService.update_profile`.

### US-207 — Sincronizar Opportunity Stage a Qualified en el CRM

Como sistema quiero reflejar en wacrm que la oportunidad pasó a Qualified cuando el perfil se completa,
para mantener consistencia entre Conversation FSM y Opportunity FSM.

```gherkin
Feature: Sincronización de Opportunity Stage
Scenario: ProfileCompleted dispara sync a CRM
  Given se publicó el evento ProfileCompleted para un Lead
  When LeadSyncAdapter.push_profile_update se ejecuta
  Then Opportunity Stage en wacrm cambia a Qualified
  And Lead.pipeline_stage local cambia a QUALIFIED
  And CRMAccessAuditORM registra el actor y la acción
```

**Alineación**
- (a) Opportunity FSM: New→Qualified (paralela a Conversation FSM, se sincronizan por evento, no es la
  misma máquina).
- (b) Capa agentic: fuera del SAS, servicio determinista (ACL/adapter).
- (c) `leads` (pipeline_stage), `crm_access_audit`, `crm_sync_cursors`.
- (d) Implementado: `LeadSyncAdapter.push_profile_update`, `Lead.mark_synced()` → `CRMStageSynced`.

### US-208 [Implementado] — Ampliar perfil a las 6 dimensiones del Customer Journey

Como Product Owner quiero que `BuyerProfile` capture financiamiento y modo de decisión (solo/pareja/
familia) para cerrar la brecha entre el Customer Journey documentado y el modelo de dominio actual.

```gherkin
Feature: Dimensiones adicionales de calificación
Scenario: Lead declara forma de pago
  Given Conversation State = Discovery
  When el lead indica contado, crédito hipotecario, crédito preaprobado o "evaluando"
  Then BuyerProfile.financing_type se actualiza (campo nuevo)
  And PROFILE_DIMENSIONS se extiende a 6 elementos (o se documenta explícitamente por qué no)
```

**Alineación**
- (a) Discovery (QUALIFICATION).
- (b) Qualification Flow — diseño únicamente.
- (c) `buyer_profiles` (migración `0006_sprint2_1_buyer_profile_dimensions`: columnas `financing_type`,
  `decision_maker_mode`).
- (d) Implementado: `FinancingType`, `DecisionMakerMode`, `PROFILE_DIMENSIONS` ahora tiene 7 elementos
  (`budget, locations, property_type, timeline, must_haves, financing_type, decision_maker_mode`),
  extractor `extract_financing_and_decision_mode` en `qualification_flow.py`.

### US-209 [Implementado] — Clasificación Hot/Warm/Cold y registro de objeciones

Como AI Agent quiero clasificar al lead en Hot/Warm/Cold y registrar objeciones (Precio, Zona,
Financiamiento, Tamaño, Tiempo) para priorizar el seguimiento comercial.

```gherkin
Feature: Calificación comercial y objeciones
Scenario: Objeción de precio detectada
  Given Conversation State = Discovery o Recommendation
  When el lead expresa resistencia relacionada a precio
  Then se registra una Objection{type: Precio, ...} vinculada al Lead
  And lead_score/classification se recalcula (Hot/Warm/Cold)
```

**Alineación**
- (a) No mapea a un estado FSM único; es transversal a Discovery/Recommendation.
- (b) Capa agentic: Objection Handler (LLM+RAG) — solo diseño en Agentic_System.md, cero código.
- (c) Tabla `lead_objections` (migración `0007_sprint2_1_lead_objections`); `leads.lead_classification`
  agregado en la misma migración.
- (d) Implementado (extracción determinista, sin LLM — el Objection Handler LLM+RAG sigue siendo
  diseño futuro per (b)): `ObjectionType`, `LeadClassification`, `Objection`, extractor
  `extract_objection`, `LeadScoringService.record_objection` recalcula `Lead.lead_score`/
  `lead_classification` (fórmula: `100 - 15*tipos_distintos - 5*total_objeciones`, umbrales
  Hot>=70, Warm 40-69.9, Cold<40 — ver design.md de `lead-objections-classification-us-209` para el
  detalle y las advertencias sobre el conflicto con `Lead.mark_synced()`).

### AI-102 [Implementado] — Extraer señales libres de la conversación hacia `conversation_memory`

Como sistema quiero extraer del texto libre del lead (adjetivos de estilo, contexto familiar, tono)
observaciones estructuradas con nivel de confianza, para tener materia prima con la que luego inferir su
perfil de afinidad, más allá de los campos duros que ya captura `BuyerProfileCaptureService`.

```gherkin
Feature: Extracción de señales conversacionales
Scenario: Lead menciona una preferencia de estilo no estructurada
  Given el lead escribe una frase con una señal de estilo/contexto (ej. "algo minimalista y luminoso")
  When el extractor NLU procesa el mensaje
  Then se inserta una fila en conversation_memory con memory_type, entity_name, value y confidence
  And la fila no sobrescribe ninguna dimensión de PROFILE_DIMENSIONS (son cosas distintas)
```

**Alineación**
- (a) Transversal a Discovery — corre en paralelo a la captura de `PROFILE_DIMENSIONS`, no reemplaza a
  `BuyerProfileCaptureService`.
- (b) Capa agentic: Requirement Extraction (`AI-102` en Backlog.md) — implementada como extracción
  determinista por palabras clave (`app/modules/conversation_memory/application/memory_extraction.py`),
  no LLM; el extractor LLM+RAG sigue siendo diseño futuro (ver design.md de
  `conversation-memory-extraction-ai-102`).
- (c) Tabla nueva `conversation_memory` (id, conversation_id, lead_id, memory_type, entity_name, value
  jsonb, confidence, created_at) — migración `0008_sprint2_1_conversation_memory`, esquema idéntico al
  propuesto en `AI_Recommendation_Domain_Model.md`.
- (d) Implementado (`MemoryType.STYLE_PREFERENCE`, `MemoryType.FAMILY_CONTEXT`; `MemoryType.TONE` queda
  como valor de enum sin extractor todavía). US-211 (sub-sprint 2.2, affinity-profile-aggregation-us-211)
  ya consume esta tabla: `ProfileAggregationService` sintetiza las observaciones en
  `buyer_profiles.ai_profile` y `leads.buyer_persona`.

### US-211 — Agregar `conversation_memory` en `ai_profile` y `buyer_persona`

Como sistema quiero sintetizar las observaciones acumuladas en `conversation_memory` en dos snapshots
distintos — `ai_profile` (por requirement/buyer profile, para scoring del Ranking Engine) y
`buyer_persona` (por lead, para el tono conversacional del Coordinator) — para que el Matching Engine
tenga una señal de afinidad real más allá de budget/zona/tipo.

```gherkin
Feature: Agregación de perfil de afinidad
Scenario: Suficientes observaciones acumuladas
  Given N filas de conversation_memory para un lead con confidence >= umbral
  When el agregador se ejecuta (recalculado solo cuando cambian las observaciones, no en cada búsqueda)
  Then buyer_profiles.ai_profile (o campo equivalente) se actualiza con scores (ej. modern_score, family_score)
  And leads.buyer_persona se actualiza por separado con señales de tono/comunicación
  And ninguno de los dos sobrescribe al otro (dueños y consumidores distintos)
```

**Alineación**
- (a) Transversal — alimenta Recommendation (RECOMMENDATION) vía Ranking Engine, y toda la Conversation
  FSM vía tono del Coordinator.
- (b) Capa agentic: servicio propio de síntesis — `ProfileAggregationService`
  (`conversation_memory/application/profile_aggregation.py`, affinity-profile-aggregation-us-211),
  invocado por el caller tras una extracción AI-102 no vacía (nunca en el camino de búsqueda).
- (c) Implementado: columnas `buyer_profiles.ai_profile` jsonb y `leads.buyer_persona` jsonb —
  migración `0009_sprint2_2_affinity_profile`.
- (d) Implementado (agregación determinista por frecuencia de keywords, umbral `confidence >= 0.5`;
  scoring LLM queda como iteración futura, misma postura que AI-102). Desbloquea a US-305 (Ranking)
  para usar `ai_profile` como señal de afinidad real — el wiring en el Ranking Engine es scope de US-305.

---

## Epic 3 — Recommendation Engine

> El backlog trata "Recommendation Engine" como una caja única (US-301). Se descompone en 6 HUs
> siguiendo el pipeline real de `app/modules/recommendation/`: ingestion → structured filter →
> semantic retrieval → ranking → explanation → neighborhood enrichment, más 3 HUs de gap de
> infraestructura y persistencia.

### US-302 — Ingestar y mantener actualizado el catálogo local de propiedades

Como sistema quiero sincronizar propiedades desde InventorySource y recalcular su embedding solo cuando
cambia el contenido, para evitar recomputar innecesariamente.

```gherkin
Feature: Ingestion de propiedades
Scenario: Propiedad modificada en el inventario
  Given una propiedad externa cuyo content_hash cambió desde el último pull
  When PropertyIngestionService.ingest_from_source se ejecuta
  Then Property local se actualiza (upsert)
  And PropertyEmbedding se recalcula solo si content_hash difiere
```

**Alineación**
- (a) No es un estado de Conversation FSM; es un proceso de soporte previo a Recommendation.
- (b) Capa agentic: Matching Engine (servicio determinista, fuera del SAS) — parcialmente implementado.
- (c) `properties`, `property_embeddings`.
- (d) Implementado: `PropertyIngestionService.ingest_from_source`, `HashEmbeddingModel` (stand-in 16-dim,
  no modelo real — gap en US-308).

### US-303 — Filtrar candidatos duros por SQL en vez de Python

Como sistema quiero que el filtro estructurado (budget, zona, tipo) se ejecute como WHERE en SQL para
evitar cargar toda la organización en memoria.

```gherkin
Feature: Filtro estructurado en SQL
Scenario: Buscar candidatos dentro de presupuesto y zona
  Given BuyerProfile.budget, locations, property_type definidos
  When StructuredFilterService.filter_candidates se ejecuta
  Then la consulta usa WHERE en la tabla properties (no list_for_organization + filtro en Python)
  And retorna únicamente candidatos que matchean hard filters
```

**Alineación**
- (a) Recommendation (RECOMMENDATION).
- (b) Matching Engine — SQL filters (diseño en Agentic_System.md); implementación actual NO cumple el
  diseño (filtra en Python).
- (c) `properties` (requiere reconciliación de columnas: `zone` vs `District`/`name_address`, ver
  US-309).
- (d) Implementado (`PropertyRepository.filter_candidates` compone el WHERE en SQL — org + BETWEEN de
  precio + `district IN` + tipo; `StructuredFilterService` delega y ya no carga el catálogo en Python;
  `matches_hard_filters` queda como especificación ejecutable del dominio —
  sprint-3-2-hybrid-retrieval-sql).

### US-304 — Migrar retrieval semántico a pgvector real

Como sistema quiero ejecutar la búsqueda por similitud usando el operador `<->` de pgvector en vez de
cosine similarity en Python, para escalar más allá de catálogos pequeños.

```gherkin
Feature: Retrieval semántico con pgvector
Scenario: Buscar propiedades semánticamente similares al perfil
  Given property_embeddings.vector es de tipo vector(1536) con índice HNSW
  When SemanticRetrievalService.retrieve se ejecuta
  Then la consulta usa el operador <-> de pgvector
  And no se calcula _cosine_similarity en Python
```

**Alineación**
- (a) Recommendation (RECOMMENDATION).
- (b) Matching Engine — pgvector (diseño); extensión `vector` 0.8.2 ya instalada en Supabase pero sin
  usar.
- (c) `property_embeddings` (columna `vector` es hoy `jsonb`, requiere migración a `vector(1536)` +
  índice HNSW — mismo gap ya identificado en `plan-implementacion-tablas-supabase.md`).
- (d) Implementado (`PropertyRepository.semantic_search` ordena por `<->` con `vector_cosine_ops` en
  Postgres — cero cosine en Python en esa ruta; índice HNSW vía migración `0013`; en SQLite/tests se
  conserva el fallback en memoria, mismo trade-off documentado del repo —
  sprint-3-2-hybrid-retrieval-sql). La calidad del query embedding (`embed_query` real) queda como
  mejora futura.

### US-305 — Rankear candidatos por señales ponderadas

Como AI Agent quiero ordenar los candidatos filtrados por un score determinista basado en señales
ponderadas para devolver los más relevantes primero.

```gherkin
Feature: Ranking determinista
Scenario: Rankear candidatos tras filtro y retrieval
  Given una lista de candidatos con RankingSignal(name, weight, value)
  When WeightedRankingEngine.rank se ejecuta
  Then score = Σ(signal.weight × value) para cada candidato
  And los candidatos se ordenan de mayor a menor score
```

**Alineación**
- (a) Recommendation (RECOMMENDATION).
- (b) Matching Engine — determinista, sin LLM. YA implementado.
- (c) Ninguna tabla propia (opera en memoria sobre resultados de US-303/US-304); persistencia en US-310.
- (d) Implementado: `WeightedRankingEngine`, `RankedCandidate.top_signals()`.

### US-306 — Generar explicación en lenguaje natural sin alterar el ranking

Como comprador quiero recibir una explicación breve de por qué se me recomienda cada propiedad para
entender la relevancia sin necesitar que el LLM invente criterios.

```gherkin
Feature: Explicación de recomendación
Scenario: Traducir señales ya rankeadas a texto
  Given un RankedCandidate con top_signals() ya calculado
  When ExplanationGenerator.explain se ejecuta
  Then el phraser recibe solo las señales seleccionadas (nunca la lista completa)
  And el texto generado no modifica el score ni el orden del candidato
```

**Alineación**
- (a) Recommendation (RECOMMENDATION).
- (b) Explanation — implementado hoy como servicio template-based no-LLM; `SignalPhraser` Protocol
  permite swap a LLM después sin tocar el resto del pipeline.
- (c) Ninguna tabla propia hoy; debería persistir en `recommendations.explanation` (US-310).
- (d) Implementado: `ExplanationGenerator`, `TemplatePhraser`.

### US-307 — Enriquecer recomendación con datos de vecindario (best-effort)

Como comprador quiero ver información de vecindario (colegios, tiempo a puntos de interés) junto a cada
propiedad recomendada, tolerando que el enriquecimiento falle sin bloquear la respuesta.

```gherkin
Feature: Enriquecimiento de vecindario
Scenario: Timeout parcial en la consulta externa
  Given una lista de propiedades rankeadas
  When NeighborhoodEnrichmentAdapter.enrich_top3 se ejecuta con timeout
  Then las propiedades sin respuesta a tiempo se envían sin NeighborhoodInsight
  And se publica NeighborhoodEnriched para reintento tardío
```

**Alineación**
- (a) Recommendation (RECOMMENDATION), no bloqueante.
- (b) Servicio determinista fuera del SAS (fan-out/fan-in).
- (c) Persiste en `recommendations.neighborhood` (jsonb), implementado en US-310.
- (d) Implementado: `NeighborhoodEnrichmentAdapter`, `GoogleMapsClient` con `google_maps_api_key`
  configurable (`Settings`, opcional — sin key no hay llamadas de red) y resolución de ubicación real
  vía `PropertyLocationPort`/`SqlPropertyLocationLookup` (antes se usaba el `property_id` como
  placeholder); evento `NeighborhoodEnriched` ya modelado.

### US-308 — Reemplazar embedding stand-in por modelo real

Como sistema quiero usar un modelo de embeddings real (no `HashEmbeddingModel` de 16 dimensiones
determinista) para que la similitud semántica sea significativa.

```gherkin
Feature: Modelo de embeddings productivo
Scenario: Generar embedding real de una propiedad
  Given el texto descriptivo de una propiedad
  When el modelo de embeddings productivo procesa el texto
  Then se genera un vector de 1536 dimensiones (OpenAI text-embedding-3-small, ya confirmado en el plan
       de tablas)
  And se persiste en property_embeddings.vector como vector(1536)
```

**Alineación**
- (a) Soporte a Recommendation (RECOMMENDATION), previo al retrieval.
- (b) Fuera del SAS, servicio de infraestructura.
- (c) `property_embeddings`.
- (d) Implementado (`OpenAIEmbeddingModel`, `infrastructure/embedding_model.py` — seam async, selección
  por `openai_api_key` con fallback determinista logueado; migración `0011` convierte
  `property_embeddings.vector` a `vector(1536)`; sprint-3-1-recommendation-schema-persistence).
  Desbloquea a US-304 (operador `<->`, Sprint 3.2).

### US-309 — Reconciliar esquema de `properties`

Como equipo de plataforma quiero que el ORM de `properties` refleje el esquema real de Supabase para
eliminar el drift entre `zone` (esperado por el ORM) y `District`/`name_address`/`Link_references`/
`estado` (agregadas manualmente fuera de Alembic).

```gherkin
Feature: Reconciliación de esquema properties
Scenario: Migración Alembic alinea columnas
  Given el ORM espera properties.zone y Supabase tiene District/name_address/Link_references/estado
  When se aplica la migración de reconciliación (0006)
  Then el atributo zone del ORM mapea a la columna District
  And name_address, Link_references, estado quedan formalizados en el modelo ORM y el dominio Property
```

**Alineación**
- (a) Soporte transversal a Recommendation, bloquea US-303 (filtro SQL confiable).
- (b) N/A (infraestructura de datos, no agentic).
- (c) `properties`.
- (d) Implementado (migración `0010_sprint3_1_properties_reconciliation`, condicional al estado real de la
  BD — cubre tanto la BD fresca de 0004 como el drift manual de Supabase; `PropertyORM.zone` mapea a la
  columna snake_case `district`; `name_address`/`estado`/`link_references` jsonb formalizados en ORM y
  dominio; sprint-3-1-recommendation-schema-persistence). Desbloquea a US-303.

### US-310 — Persistir RecommendationResult en tabla `recommendations`

Como Product Owner quiero que cada resultado de búsqueda de recomendación se persista (candidatos,
señales, explicación, vecindario, feedback) para poder auditar decisiones y alimentar el learning loop,
en vez de que `RecommendationResult` sea efímero.

```gherkin
Feature: Persistencia de recomendaciones
Scenario: Guardar sesión de recomendación
  Given RecommendationService.search() completó ranking + explanation + enrichment
  When el resultado se retorna al llamador (hoy: wiring.handle_profile_completed)
  Then se inserta una fila en recommendations por cada property_id rankeado
  And se registran rank, score, signals (jsonb), explanation, neighborhood (jsonb), generated_at
  And delivered_at y feedback se actualizan en eventos posteriores
```

**Alineación**
- (a) Cierra US-301 del backlog ("store Recommendation Session"); estado Recommendation
  (RECOMMENDATION).
- (b) Hoy la orquestación vive en `wiring.py` (sin Coordinator todavía); el Coordinator (AI-104) sería el
  responsable natural una vez exista.
- (c) Tabla nueva `recommendations` (id, organization_id, lead_id, buyer_profile_id, property_id, rank,
  score, signals jsonb, explanation, neighborhood jsonb, feedback jsonb, generated_at, delivered_at) con
  RLS — mismo diseño ya presentado en `plan-implementacion-tablas-supabase.md`.
- (d) Implementado (migración `0012_sprint3_1_recommendations` con RLS; `RecommendationService.search()`
  persiste vía `RecommendationRepository` una fila por item con `signals` jsonb dinámico;
  `wiring.handle_profile_completed` estampa `delivered_at` tras publicar `ResponseReady`; `feedback`
  queda nullable para eventos futuros; sprint-3-1-recommendation-schema-persistence). Cierra US-301.

### AI-104 [Implementado — alcance corregido] — Coordinator Agent y Intent Router LLM-backed

> **2026-07-25 corrección de alcance** (`openspec/changes/intent-router-ai-104/`): el Coordinator
> Agent descrito abajo YA estaba implementado (`CoordinatorAgent.handle_message` en
> `coordinator.py`, con guardrail interceptor, identity gate, qualification turn y registro de
> `AIDecisionTrace` vía `trace_decision`) — la premisa `[GAP — no implementado]` original estaba
> desactualizada. Lo único que realmente faltaba era el Intent Router LLM-backed (mismo gap ya
> documentado por separado en AI-105 más abajo). Ese Intent Router quedó implementado por este
> change: `IntentRouterPort`/`GeminiIntentRouter`/`KeywordIntentRouter`
> (`app/modules/conversation_ownership/application/intent_router.py`), invocado desde
> `CoordinatorAgent._classify_intent` (después del guardrail bypass, antes del identity gate) y
> registrado como `tool_call` en el `AIDecisionTrace` existente — sin nueva tabla ni columna. El
> resultado de la clasificación aún no determina ninguna rama de `handle_message` (no-goal
> explícito del design.md); consumir la categoría para enrutar de verdad queda como iteración
> futura una vez validado el set de categorías contra tráfico real.

Como sistema quiero un Coordinator Agent (SAS) que orqueste toda la conversación y delegue a
Qualification Flow, Objection Handler y Matching Engine según la intención detectada por el Intent
Router (1 llamada LLM, 6 categorías), reemplazando la orquestación actual hardcodeada en `wiring.py`.

```gherkin
Feature: Orquestación conversacional agéntica
Scenario: Router clasifica intención y delega
  Given un mensaje entrante del lead
  When el Intent Router lo clasifica en una de 6 categorías
  Then el Coordinator Agent delega al sub-flujo correspondiente
  And decisiones no conversacionales (matching, scheduling) se delegan a servicios deterministas
  And se registra un AIDecisionTrace en ai_decision_traces
```

**Alineación**
- (a) Transversal a Discovery/Recommendation/Scheduling (todo el Conversation FSM).
- (b) Coordinator Agent — YA implementado (`CoordinatorAgent.handle_message`); Intent Router —
  implementado por `intent-router-ai-104` (`IntentRouterPort`, invocado antes del identity gate,
  aún sin consumir la categoría para enrutar — ver nota de alcance arriba).
- (c) `ai_decision_traces` (ya consumida por `trace_decision`/`DecisionTraceRecorder`,
  `tool_calls` incluye ahora `intent_router.classify`), `conversations`.
- (d) Implementado: `CoordinatorAgent` (guardrail → identity gate → qualification turn →
  conversational turn, con `AIDecisionTrace` por turno) + `IntentRouterPort`/
  `GeminiIntentRouter`/`KeywordIntentRouter` (`intent_router.py`). Pendiente (fuera de este
  change): que la categoría clasificada determine la rama ejecutada.

---

## Tabla resumen

| ID | Título breve | Estado FSM | Capa agentic | Tabla(s) | Implementado hoy |
|----|--------------|-----------|---------------|----------|-------------------|
| US-202 | Capturar presupuesto | Discovery (QUALIFICATION) | Qualification Flow (`extract_budget` en `qualification_flow.py`, invocado por `CoordinatorAgent` vía `run_qualification_turn` en cada turno real — qualification-flow-us-202-205) | buyer_profiles | Implementado |
| US-203 | Capturar ubicación | Discovery (QUALIFICATION) | Qualification Flow (`extract_locations` en `qualification_flow.py`, invocado por `CoordinatorAgent` vía `run_qualification_turn` en cada turno real — qualification-flow-us-202-205) | buyer_profiles | Implementado |
| US-204 | Capturar tipo de propiedad | Discovery (QUALIFICATION) | Qualification Flow (`extract_property_type` en `qualification_flow.py`, invocado por `CoordinatorAgent` vía `run_qualification_turn` en cada turno real — qualification-flow-us-202-205) | buyer_profiles | Implementado |
| US-205 | Capturar timeline y must-haves | Discovery (QUALIFICATION) | Qualification Flow (`extract_timeline_and_must_haves` en `qualification_flow.py`, invocado por `CoordinatorAgent` vía `run_qualification_turn` en cada turno real — qualification-flow-us-202-205) | buyer_profiles | Implementado |
| US-206 | Completeness Gate | Discovery→Recommendation | Guardrail no-LLM | buyer_profiles, leads, outbox_events | Sí |
| US-207 | Sync Opportunity Stage=Qualified | Opportunity FSM (paralela) | Servicio determinista (ACL) | leads, crm_access_audit, crm_sync_cursors | Sí |
| US-208 | Ampliar a 7 dimensiones (financing_type, decision_maker_mode) | Discovery (QUALIFICATION) | Qualification Flow (extractor `extract_financing_and_decision_mode` — buyer-profile-dimensions-us-208) | buyer_profiles | Sí |
| US-209 | Hot/Warm/Cold + objeciones | Transversal | Qualification Flow extractor + LeadScoringService (determinista; Objection Handler LLM+RAG sigue en diseño) | lead_objections, leads (lead_classification) | Sí |
| AI-102 | Extraer señales libres a conversation_memory | Transversal (Discovery) | Requirement Extraction (extractor determinista, `conversation_memory` module — conversation-memory-extraction-ai-102) | conversation_memory (nueva) | Sí |
| US-211 | Agregar ai_profile / buyer_persona | Transversal | Síntesis determinista (`ProfileAggregationService`, `conversation_memory` module — affinity-profile-aggregation-us-211) | buyer_profiles.ai_profile, leads.buyer_persona (nuevas) | Sí |
| US-302 | Ingestion de propiedades | Soporte previo a Recommendation | Matching Engine | properties, property_embeddings | Sí |
| US-303 | Filtro estructurado en SQL | Recommendation (RECOMMENDATION) | Matching Engine (SQL filters — `PropertyRepository.filter_candidates`, sprint-3-2-hybrid-retrieval-sql) | properties | Sí |
| US-304 | Retrieval semántico pgvector | Recommendation (RECOMMENDATION) | Matching Engine (pgvector `<->` + HNSW, fallback en memoria solo en SQLite — sprint-3-2-hybrid-retrieval-sql) | property_embeddings | Sí |
| US-305 | Ranking ponderado | Recommendation (RECOMMENDATION) | Matching Engine | — (en memoria) | Sí |
| US-306 | Explicación en lenguaje natural | Recommendation (RECOMMENDATION) | Explanation (template, swap a LLM) | — (en memoria) | Sí |
| US-307 | Enriquecimiento de vecindario | Recommendation (RECOMMENDATION) | Servicio determinista fan-out/fan-in, `google_maps_api_key` + `PropertyLocationPort` | recommendations.neighborhood (jsonb) | Sí |
| US-308 | Modelo de embeddings real | Soporte a Recommendation | Infraestructura (`OpenAIEmbeddingModel`, seam async con fallback determinista) | property_embeddings | Sí |
| US-309 | Reconciliar esquema properties | Soporte a Recommendation | N/A (datos — migración 0010 condicional) | properties | Sí |
| US-310 | Persistir recommendations | Recommendation (RECOMMENDATION) | `RecommendationService` persiste; Coordinator (AI-104) heredará la orquestación | recommendations (nueva) | Sí |
| AI-104 | Coordinator Agent + Intent Router | Transversal a toda la Conversation FSM | Coordinator (ya implementado) + Intent Router (`intent-router-ai-104`, clasifica y ahora enruta objeción/Q&A — `intent-router-llm-ai-105`) | ai_decision_traces, conversations | Sí (alcance corregido) |
| US-212 [NUEVA] | Conectar Availability Validator + Scheduling al flujo | Recommendation→Scheduling | Wiring en CoordinatorAgent sobre servicios ya implementados (`scheduling_turn.py`, `openspec/changes/scheduling-wiring-us-212`) | appointments, leads.pipeline_stage | Sí |
| US-213 [NUEVA] | Reminder Scheduler real (24h/2h) | Transversal a Scheduling | Reemplaza NoOpReminderScheduler | outbox_events | No [GAP], depende de US-212 |
| AI-105 [Implementado — alcance corregido] | Intent Router (1 llamada LLM, N categorías) | Transversal | Clasificación ya implementada por AI-104; este change wirea la categoría clasificada a `KnowledgeService.answer` para `objecion`/`pregunta_informativa` (`intent-router-llm-ai-105`) | ai_decision_traces | Sí (alcance corregido) |
| AI-106 [Implementado] | Knowledge/RAG Service (Objeción + Q&A) | Transversal | `KnowledgeService.answer` standalone, ahora wireado a `CoordinatorAgent` para `objecion`/`pregunta_informativa` (`intent-router-llm-ai-105`) | knowledge_documents (nueva, migración 0021) | Sí |
| US-214 [Implementado] | LeadReadinessService (score continuo + financing readiness) | Transversal | Extiende LeadScoringService de forma aditiva (`lead_readiness.py` — lead-readiness-service-us-214) | buyer_profiles.readiness_score / financing_readiness (migración 0020) | Sí |
| US-215 [ADAPTADA de US-206] | Bajar umbral de Completeness Gate | Discovery→Recommendation | Config de CompletenessGate existente | buyer_profiles, leads, outbox_events | No [config pendiente] |
| US-216 [ADAPTADA] | Tono conversacional + resumen cada 2 respuestas | Discovery (QUALIFICATION) | Prompt (DEFAULT_SYSTEM_PROMPT) | — | Sí [prompt reescrito] |
| US-217 [ADAPTADA de US-202..205] | Reordenar preguntas Nivel 1 / Nivel 2 | Discovery (QUALIFICATION) | Orden de extractores existentes | buyer_profiles | No [orquestación pendiente] |
| US-218 [Implementado] | Diferir captura de identidad (DNI) | New→Discovery | Reordena Identity Gate en coordinator.py | leads | Sí [`_dni_gate` + `REPROMPT_DNI`] |
| US-219 [NUEVA] | Motivación + preguntas adaptativas por tipo | Discovery (QUALIFICATION) | Nuevo extractor `extract_motivation` | buyer_profiles (columna nueva) | No [GAP] |
| US-220 [Implementado] | Turno de profundización pre-agenda | Recommendation→Scheduling | Orquestación determinística (`deepening_turn.py`) tras el narrator | — | Sí [`run_deepening_turn` + `RecommendationRepository.mark_selected` vía columna `feedback` existente] |
| US-221 [ADAPTADA de US-212] | Invitación conversacional a visita | Recommendation→Scheduling | Prompt sobre wiring de US-212 | — | No [bloqueada por US-212] |

## Epic 4 — Backlog de Conversión (propuesta 2026-07-25, HUs nuevas/adaptadas)

> Origen: análisis de una propuesta de mejora de flujo conversacional (conversación no-formulario,
> recomendación temprana, agendamiento con lenguaje natural) contrastada contra el estado real del
> código (`Agentic_System.md` §12, re-verificado con Explore el 2026-07-25). Cada HU se marca
> **[NUEVA]** (capacidad sin código hoy) o **[ADAPTADA — ver US-XXX]** (modifica el comportamiento de
> una HU ya implementada, sin duplicar su documentación). Numeración continúa desde US-211 / AI-104.
> Dos ideas de la propuesta se **rechazan explícitamente** (ver nota al final de la sección) por
> fragmentar responsabilidades ya resueltas correctamente por servicios deterministas existentes.

### P0 — Wiring puro (cero rebuild, servicios ya construidos y probados en aislamiento)

#### US-212 [NUEVA] — Conectar Availability Validator + Scheduling Service al flujo conversacional

Como sistema quiero que `CoordinatorAgent` invoque `AvailabilityValidatorService` y
`SchedulingService.book_visit` cuando el lead acepta un horario, para que exista agendamiento real en
producción (hoy ambos servicios están completos y testeados de forma aislada, pero ningún nodo del grafo
ni `coordinator.py` los llama — confirmado por ausencia total de imports de `appointment` en
`coordinator.py`).

```gherkin
Feature: Agendamiento conectado al flujo conversacional
Scenario: Lead acepta un horario propuesto
  Given Conversation State = Recommendation (RECOMMENDATION) y un horario ya validado por
        AvailabilityValidatorService
  When el lead confirma el horario en el turno conversacional
  Then CoordinatorAgent invoca SchedulingService.book_visit (re-valida disponibilidad internamente)
  And se crea el evento en Google Calendar y se persiste Appointment
  And se publica AppointmentBooked y Lead.pipeline_stage sincroniza APPOINTMENT_SET a wacrm
```

**Alineación**
- (a) Recommendation → Scheduling (RECOMMENDATION→SCHEDULING, transición hoy inexistente en código).
- (b) Capa agentic: llamada directa desde `CoordinatorAgent.handle_message` (mismo patrón determinista
  que `run_qualification_turn`), no requiere LLM adicional — solo un nuevo paso de orquestación.
- (c) Tablas ya existentes: `appointments` (US-402/404), `leads.pipeline_stage`.
- (d) [GAP de wiring, no de servicio] `AvailabilityValidatorService` y
  `SchedulingService.book_visit` (`app/modules/appointment/application/`) están implementados y
  probados (`tests/test_availability_validator.py`, `tests/test_scheduling_service.py`); falta
  exclusivamente el paso en `coordinator.py` que los invoque.

#### US-213 [NUEVA] — Implementar Reminder Scheduler real (24h/2h)

Como sistema quiero reemplazar `NoOpReminderScheduler` por una implementación real que programe
recordatorios 24h y 2h antes de la visita, para reducir el no-show.

```gherkin
Feature: Recordatorios de visita
Scenario: Visita agendada con más de 24h de anticipación
  Given un Appointment confirmado vía SchedulingService.book_visit
  When faltan 24h para la visita
  Then el lead recibe un recordatorio por WhatsApp
  And 2h antes recibe un segundo recordatorio
  And ambos envíos quedan trazados (idempotentes ante reintentos del outbox)
```

**Alineación**
- (a) Transversal a Scheduling (SCHEDULING), posterior a US-212.
- (b) Servicio determinista fuera del SAS — implementa `ReminderSchedulerPort`
  (`app/modules/appointment/application/reminder_port.py`), hoy solo `NoOpReminderScheduler` (stub
  explícito documentado como placeholder de US-405).
- (c) Reutiliza `outbox_events` (con el backoff de `alembic/versions/0019_outbox_retry_backoff.py`) para
  el envío programado.
- (d) [GAP] No implementado — depende de US-212 (sin agendamiento real, no hay fecha de visita sobre la
  cual programar recordatorios).

### P1 — Construcción acotada (diseñada en Agentic_System.md §1–2, pendiente de código)

#### AI-105 [Implementado — alcance corregido] — Intent Router (1 llamada LLM, N categorías)

> **2026-07-27 corrección de alcance** (`openspec/changes/intent-router-llm-ai-105/`): la
> clasificación LLM en sí (`IntentRouterPort`/`GeminiIntentRouter`/`KeywordIntentRouter`, 6
> categorías, superset de las 5 nombradas aquí) YA estaba implementada por `intent-router-ai-104`
> — la premisa `[NUEVA]`/`[GAP]` original estaba desactualizada. Lo único que faltaba, confirmado
> por la propia nota de corrección de AI-104 y por el docstring de `knowledge_service.py`
> ("NOT wired into `CoordinatorAgent.handle_message`"), era que la categoría clasificada
> determinara alguna rama real. Este change cierra exactamente ese gap: `_classify_intent` ahora
> retorna la categoría, y `CoordinatorAgent` llama a `KnowledgeService.answer` (AI-106) cuando la
> categoría es `objecion` o `pregunta_informativa` — la respuesta fundamentada reemplaza la
> respuesta del LLM conversacional cuando hay match en la KB (`found=True`); sin match o ante
> cualquier fallo, el comportamiento previo se preserva sin cambios. El resto de categorías
> (`qualification`, `agendamiento`, `handoff_explicito`, `otro`) permanecen sin rama dedicada —
> decisión de alcance explícita, ver `design.md` de este change (Non-Goals).

Como sistema quiero clasificar cada mensaje entrante en una categoría de intención (calificación,
pregunta informativa, objeción, agendamiento, otro) mediante una única llamada LLM ligera, para
enrutar el turno sin necesidad de un agente autónomo adicional.

```gherkin
Feature: Enrutamiento por intención
Scenario: Mensaje ambiguo entre pregunta y objeción
  Given un mensaje entrante del lead
  When IntentRouter.classify se ejecuta (1 llamada LLM, salida JSON acotada a N categorías)
  Then CoordinatorAgent recibe la categoría antes de decidir el sub-flujo
  And se registra un AIDecisionTrace con la categoría y el mensaje clasificado
```

**Alineación**
- (a) Transversal — corre al inicio de `CoordinatorAgent.handle_message`, antes de `run_qualification_turn`
  / `_conversational_turn`.
- (b) Capa agentic: implementada por `intent-router-ai-104` (`IntentRouterPort`/`GeminiIntentRouter`/
  `KeywordIntentRouter`, 6 categorías) + wireada por este change (`intent-router-llm-ai-105`) —
  `_classify_intent` ahora retorna la categoría y `CoordinatorAgent` la consume.
- (c) `ai_decision_traces` (ya consumida por `trace_decision`; ahora también registra `knowledge.answer`
  como `tool_call` cuando la rama de conocimiento dispara).
- (d) Implementado (alcance acotado): `_classify_intent` deja de descartar su resultado; `objecion`/
  `pregunta_informativa` disparan `KnowledgeService.answer` (AI-106) reemplazando la respuesta del LLM
  conversacional solo cuando hay match en la KB, con fallback exacto al comportamiento previo ante
  `found=False` o cualquier excepción. `qualification`, `agendamiento` (ya tiene ruta propia vía US-212),
  `handoff_explicito` y `otro` permanecen sin rama dedicada — decisión de alcance explícita (ver
  Non-Goals en `design.md`), no un gap accidental. 6 tests nuevos cubren respuesta fundamentada,
  fallback por no-match, fallback por fallo del servicio, y no-invocación en categorías no consumidoras.

#### AI-106 [Implementado] — Knowledge/RAG Service unificado (Objection Handler + Q&A informativo)

> **2026-07-27 actualización** (`openspec/changes/knowledge-rag-service-ai-106/`): el servicio RAG en sí
> quedó implementado como `KnowledgeService.answer(organization_id, query, category=None, top_k=3)` en
> `app/modules/knowledge/` (dominio + repositorio pgvector + servicio de aplicación), tal como preveía la
> nota de dependencias de Epic 4 ("el servicio RAG se puede prototipar en paralelo con Track A"). La
> respuesta se ensambla de forma **extractiva** (sin llamada LLM libre) a partir únicamente de los pasajes
> recuperados, satisfaciendo estructuralmente la regla de "sin cifras no verificadas" sin depender de un
> guardrail post-hoc. Tabla nueva `knowledge_documents` (migración `0021`, vector(1536) + HNSW + RLS por
> `organization_id`, mirroring `property_embeddings`). El wiring que decidía cuándo invocar el servicio
> (Objeción vs Q&A) ya no es GAP: `intent-router-llm-ai-105` conecta `KnowledgeService` a
> `CoordinatorAgent.handle_message` para las categorías `objecion`/`pregunta_informativa`.

Como AI Agent quiero responder objeciones (precio, zona, plusvalía, financiamiento) y preguntas
informativas del lead con contenido fundamentado en una base de conocimiento aprobada, en vez de solo
detectar y puntuar la objeción sin responderla.

```gherkin
Feature: Respuesta fundamentada a objeciones y preguntas
Scenario: Lead pregunta por plusvalía de la zona
  Given AI-105 clasifica el mensaje como Objeción o Pregunta informativa
  When KnowledgeService.answer recupera pasajes relevantes de la KB aprobada (RAG)
  Then la respuesta se redacta solo con esos pasajes (sin cifras no verificadas — Regla 2/QA-6)
  And se reutiliza la misma infraestructura de retrieval para ambos intents (Objeción y Q&A)
```

**Alineación**
- (a) Transversal a Discovery/Recommendation (Objeción) y a cualquier estado (Q&A).
- (b) Capa agentic: **no existe hoy**. Lo único implementado es la detección/puntuación determinista
  sin respuesta generada: `qualification_flow.py::extract_objection` +
  `LeadScoringService.record_objection` (Hot/Warm/Cold, sin dimensión de financiamiento — ver US-214).
  No hay módulo de RAG, vector store de documentos ni `ObjectionHandler`/`KnowledgeService` en el repo
  (confirmado, distinto del pgvector de `property_embeddings` que indexa propiedades, no conocimiento).
- (c) Tabla nueva `knowledge_documents` (embedding vector(1536) + HNSW + RLS), fuera de `property_embeddings`.
- (d) Implementado (retrieval): `KnowledgeService.answer`, `KnowledgeRepository` (pgvector `<->` en
  Postgres, ranking coseno en Python como fallback en SQLite, mismo patrón de `property_embeddings` —
  knowledge-rag-service-ai-106); 6 tests cubren aislamiento por organización, filtro por categoría,
  solo documentos `approved=true`, grounding (la respuesta nunca contiene texto ausente de los pasajes
  recuperados) y KB vacía. El wiring hacia `CoordinatorAgent` (antes pendiente de AI-105) quedó cerrado
  por `intent-router-llm-ai-105` — ver Alineación (d) de AI-105 arriba para el detalle de la rama.

#### US-214 [Implementado] — LeadReadinessService: score continuo + urgencia + readiness financiera

Como AI Agent quiero un score continuo ponderado (intención, presupuesto, zona, horizonte, forma de
pago, decisor) además de la clasificación Hot/Warm/Cold binaria por objeciones, y una readiness
financiera en 3 estados (READY/PRE-READY/DISCOVERY), para alimentar tanto el disparo temprano de
recomendación como el Ownership Policy Engine.

```gherkin
Feature: Readiness continua del lead
Scenario: Perfil parcial pero con señales fuertes de urgencia
  Given BuyerProfile con financing_type, timeline y locations capturados (no todas las 7 dimensiones)
  When LeadReadinessService.evaluate se ejecuta
  Then retorna un score continuo ponderado (no solo Hot/Warm/Cold)
  And clasifica financing_readiness en READY, PRE-READY o DISCOVERY
  And el resultado alimenta tanto al Coordinator (trigger de recomendación temprana, US-215) como al
      OwnershipPolicyEngine
```

**Alineación**
- (a) Transversal a Discovery/Recommendation.
- (b) Capa agentic: **no existe** — confirmado, no hay símbolo `LeadReadiness`/`PRE-READY`/`PRE_READY`
  en `app/`. Extiende (no reemplaza) `LeadScoringService`
  (`app/modules/lead_qualification/application/lead_scoring.py`, umbrales
  `_HOT_THRESHOLD`/`_WARM_THRESHOLD` ya existentes) — mismo servicio, nueva dimensión de salida.
- (c) Extiende `buyer_profiles` con columnas `readiness_score` y `financing_readiness` (migración `0020`,
  nullable — perfiles existentes simplemente no tienen readiness calculado hasta que `evaluate()` corre).
- (d) Implementado: `LeadReadinessService.evaluate` (`app/modules/lead_qualification/application/
  lead_readiness.py` — lead-readiness-service-us-214) suma puntos ponderados por señal (property_type 15,
  budget 20, locations 15, timeline 2–20 según urgencia, financing_type 8–20 según fuerza, decision_maker_mode
  10; clamp `[0,100]`) y clasifica `FinancingReadiness` en READY/PRE_READY/DISCOVERY. Aditivo: no modifica
  `LeadScoringService.record_objection` ni sus umbrales Hot/Warm/Cold existentes (15 tests, incluida
  regresión de `test_lead_objections.py`). `OwnershipPolicyEngine` confirmado ausente del repo — el
  resultado queda producido pero sin consumidor todavía (fuera de alcance de este change).

#### US-215 [ADAPTADA — ver US-206] — Bajar el umbral de Completeness Gate (recomendación-first)

Como Product Owner quiero recalibrar `profile_completeness_threshold` (hoy 90%, `app/core/config.py:42`)
a un valor más bajo para disparar `ProfileCompleted`/Matching con ~4 dimensiones capturadas en vez de
esperar el perfil casi completo, mejorando el time-to-first-recommendation sin reconstruir el pipeline.

```gherkin
Feature: Recomendación temprana
Scenario: Perfil con 4 dimensiones núcleo capturadas
  Given BuyerProfile con budget, locations, property_type y timeline capturados (no financing_type ni
        must_haves ni decision_maker_mode)
  When completeness(profile) >= nuevo umbral recalibrado (< 90%)
  Then CompletenessGate.can_advance_to_recommendation retorna can_advance = true
  And se dispara Matching con esas 4 dimensiones; el resto se captura como refinamiento posterior
      (Nivel 2, ver US-217)
```

**Alineación**
- (a) Discovery→Recommendation (mismo evento `ProfileCompleted` de US-206, no una transición nueva).
- (b) Config de servicio existente — `CompletenessGate.can_advance_to_recommendation`
  (`app/modules/lead_qualification/application/completeness_gate.py:31`) ya acepta un `threshold`
  explícito; no requiere cambio de código, solo de configuración/valor default.
- (c) `buyer_profiles`, `leads`, `outbox_events` (mismas de US-206, sin tabla nueva).
- (d) [ADAPTA A US-206] Único cambio real: bajar `profile_completeness_threshold` en
  `app/core/config.py` y validar con datos que el umbral nuevo no dispara recomendaciones con perfiles
  demasiado vacíos (riesgo: falsos positivos de Matching con 0 candidatos — mitigado por
  `search_diagnostics.py`, ver nota más abajo).

### P2 — Prompt y diseño conversacional (cero cambio de arquitectura)

#### US-216 [Implementado — ver DEFAULT_SYSTEM_PROMPT en prompts.py] — Tono conversacional con resumen cada 2 respuestas

Como lead quiero una conversación fluida (no formulario) con un resumen breve de lo entendido cada 2
respuestas, en vez de una batería de preguntas secas.

```gherkin
Feature: Conversación no-formulario
Scenario: Lead responde 2 preguntas consecutivas
  Given DEFAULT_SYSTEM_PROMPT (prompts.py) ya rige el tono del nodo respond
  When el lead completa su segunda respuesta consecutiva de calificación
  Then la siguiente respuesta del asistente incluye un resumen breve de lo entendido antes de la
       siguiente pregunta
  And el tono se mantiene cálido-profesional (emojis con moderación)
```

**Alineación**
- (a) Discovery (QUALIFICATION) — no cambia el estado FSM, solo el prompt.
- (b) Prompt únicamente — `DEFAULT_SYSTEM_PROMPT` (`app/modules/conversation_ownership/domain/prompts.py`,
  ya freeform y cubre greeting/qualification/recommendation/handoff en un solo prompt, con override por
  organización vía Prompt Registry en `coordinator.py::_load_system_prompt`).
- (c) Ninguna tabla nueva; usa el mismo Prompt Registry ya existente.
- (d) Implementado (conversational-tone-us-216): `DEFAULT_SYSTEM_PROMPT` reescrito con guía de
  conversación no-formulario, instrucción explícita de resumen cada 2 respuestas consecutivas de
  calificación, y tono cálido-profesional con uso moderado de emojis; todas las reglas anti-alucinación y
  anti-inyección existentes se preservaron intactas. Sin cambio de código en `llm_brain.py` ni en el
  grafo — la cadencia de resumen es auto-rastreada por el LLM vía el historial de la conversación (no
  existe contador de turnos en el modelo de dominio). 6 tests nuevos en `tests/test_prompts.py`.

#### US-217 [ADAPTADA — ver US-202 a US-205] — Reordenar preguntas: Nivel 1 obligatorio / Nivel 2 refinamiento

Como AI Agent quiero disparar preguntas de Nivel 1 (intención, tipo, ubicación, presupuesto, horizonte)
antes que las de Nivel 2 (dormitorios, amenidades, mascotas, piso), para alcanzar el umbral de US-215
más rápido.

```gherkin
Feature: Secuencia de preguntas por nivel
Scenario: Conversación nueva sin perfil previo
  Given un Lead recién vinculado sin BuyerProfile capturado
  When qualification_flow.* dispara extractores
  Then budget, locations, property_type y timeline se solicitan antes que must_haves de refinamiento
  And una vez alcanzado el umbral de US-215, las preguntas de Nivel 2 se formulan como refinamiento
      post-recomendación, no como bloqueo previo
```

**Alineación**
- (a) Discovery (QUALIFICATION).
- (b) Prompt + orden de servicio existente — reordena la secuencia de disparo de los extractores ya
  implementados en `qualification_flow.py` (`extract_budget`, `extract_locations`,
  `extract_property_type`, `extract_timeline_and_must_haves`); no crea extractores nuevos.
- (c) `buyer_profiles` (mismas columnas de US-202 a US-205).
- (d) [ADAPTA] Cambio de orquestación/prompt, no de dominio — `BuyerProfile.apply(patch)` ya soporta
  actualización parcial e incremental, requisito para que Nivel 2 llegue después sin bloquear.

#### US-218 [Implementado — ver Identity Gate en coordinator.py] — Mover captura de identidad después de mostrar valor

Como lead quiero que no se me pida DNI/nombre completo en el primer turno, sino después de recibir una
recomendación o valor percibido, para reducir abandono temprano.

```gherkin
Feature: Captura de identidad diferida
Scenario: Primer turno del lead
  Given un mensaje entrante sin Lead vinculado todavía
  When CoordinatorAgent.handle_message ejecuta el identity gate
  Then el saludo inicial no exige DNI; solo nombre/canal mínimos para crear el Lead en wacrm
  And la captura de datos sensibles (DNI) se pospone hasta después de GeminiRecommendationNarrator.narrate
      o de un intercambio de valor equivalente
```

**Alineación**
- (a) New→Discovery (QUALIFICATION), previo a la primera recomendación.
- (b) Prompt/orquestación — modifica el orden dentro de `_identity_gate` /
  `extract_identity` (`coordinator.py`), que hoy corre siempre antes de `run_qualification_turn`;
  no elimina la captura, solo reordena qué campos son obligatorios en qué turno.
- (c) `leads` (sin cambio de esquema).
- (d) Implementado: se validó el contrato real de wacrm (`WacrmClient.create_lead` /
  `WACRM_API_Adaptation_Plan.md`) — `POST /deals` exige `contact_phone` (ya conocido del canal) y
  `contact_name` (`str` no-opcional); `contact_dni` ya era opcional. Conclusión: el nombre sigue siendo
  el identificador mínimo real, el DNI es lo único diferible. `REPROMPT_IDENTITY` ya no menciona el DNI
  en el turno 1; nuevo `REPROMPT_DNI` se muestra solo una vez `conversation.state == RECOMMENDATION`
  (`CoordinatorAgent._dni_gate`), de forma aditiva (no bloquea calificación/agendamiento). Sin cambio de
  esquema en `leads` — el propio estado `RECOMMENDATION` acota la ventana de la pregunta. Tests:
  `tests/test_coordinator_dni_gate.py`, `tests/test_coordinator_identity_gate.py`.

#### US-219 [NUEVA] — Motivación de compra y preguntas adaptativas por tipo de propiedad

Como AI Agent quiero detectar la motivación (mudanza, inversión, vacacional, primera vivienda) y adaptar
qué preguntas de Nivel 2 se formulan según `property_type` (ej. no preguntar piso si es casa), para
evitar preguntas irrelevantes.

```gherkin
Feature: Motivación y preguntas condicionales
Scenario: Lead busca casa, no departamento
  Given BuyerProfile.property_type = CASA
  When qualification_flow decide qué pregunta de Nivel 2 formular
  Then no se pregunta por piso/nivel (solo aplica a departamento)
  And se registra motivation en BuyerProfile (campo nuevo, mismo patrón que budget/timeline)
```

**Alineación**
- (a) Discovery (QUALIFICATION).
- (b) Extensión de servicio existente — nuevo extractor `extract_motivation` en `qualification_flow.py`
  (mismo patrón regex/keyword que los extractores ya implementados) + reglas condicionales
  `if property_type == CASA → skip piso`.
- (c) `buyer_profiles` (columna `motivation` nueva, migración a definir — mismo patrón de
  `0006_sprint2_1_buyer_profile_dimensions`).
- (d) [GAP] No implementado. Candidato a ampliar `PROFILE_DIMENSIONS` (hoy 7 elementos post-US-208) a 8.

#### US-220 [NUEVA] — Turno de profundización antes de proponer horario

Como AI Agent quiero preguntar "¿cuál de estas opciones te llamó más la atención?" después de
`GeminiRecommendationNarrator.narrate` y antes de invitar a agendar, para confirmar interés real antes
de invertir un slot de `AvailabilityValidatorService`.

```gherkin
Feature: Confirmación de interés antes de agendar
Scenario: Lead recibió el Top-3 narrado
  Given GeminiRecommendationNarrator.narrate ya envió el cierre del Top-3
  When el lead responde a la recomendación
  Then el siguiente turno del asistente pregunta cuál opción le interesó más antes de ofrecer horarios
  And la propiedad elegida se usa como referencia para US-212 (Availability Validator)
```

**Alineación**
- (a) Recommendation → Scheduling (RECOMMENDATION→SCHEDULING).
- (b) Orquestación determinística (no prompt-only) — nuevo turno `deepening_turn.run_deepening_turn`
  invocado desde `_conversational_turn`, posterior a la narración ya implementada
  (`llm_narrator.GeminiRecommendationNarrator.narrate`) y previo al turno de agendamiento (US-212).
  Ver `openspec/changes/pre-agenda-deepening-us-220/proposal.md` (sección "Deviations") para el porqué
  de esta desviación respecto al `(b)` original de este documento.
- (c) Ninguna tabla nueva — reutiliza la columna `RecommendationORM.feedback` ya existente.
- (d) [Implementado] US-212 ya está wireado (`scheduling-wiring-us-212`); la propiedad elegida en el
  turno de profundización se enruta a `run_scheduling_turn` vía `_latest_top_pick`.

#### US-221 [ADAPTADA — ver US-212] — Lenguaje natural de invitación a visita

Como lead quiero que la invitación a agendar sea una sugerencia conversacional ("la opción 2 se ajusta a
lo que buscas, ¿coordinamos una visita?") en vez de una pregunta binaria "¿desea agendar? sí/no".

```gherkin
Feature: Invitación conversacional a visita
Scenario: Lead mostró interés en una opción específica (US-220)
  Given US-212 ya conecta SchedulingService al flujo conversacional
  When el asistente redacta la invitación a visita
  Then el texto conecta la opción elegida con la invitación, sin formato de pregunta sí/no rígida
  And los horarios ofrecidos ya fueron pre-validados por AvailabilityValidatorService (Regla 1,
      Agentic_System.md §1.B)
```

**Alineación**
- (a) Recommendation → Scheduling (RECOMMENDATION→SCHEDULING).
- (b) Prompt únicamente, sobre el mismo paso de orquestación de US-212 — sin este último, no hay
  horarios reales que redactar en lenguaje natural.
- (c) Ninguna tabla nueva.
- (d) [ADAPTA A US-212] Bloqueada por US-212: no tiene sentido pulir el lenguaje de una invitación que
  hoy no dispara ningún agendamiento real.

### Decisiones rechazadas de la propuesta original

- **Ranking Agent / Explanation Agent como agentes LLM separados**: rechazado. `WeightedRankingEngine`
  (US-305) y `ExplanationGenerator` (US-306) ya son servicios deterministas correctamente acotados y
  probados; convertirlos en agentes fragmentaría una responsabilidad ya resuelta sin ganancia (mismo
  criterio de Agentic_System.md §1: "Regla del 45%" — un servicio determinista bien acotado supera a un
  agente LLM adicional en este tramo).
- **Requirement Profile Builder Agent separado**: rechazado. `BuyerProfileCaptureService`
  (`app/modules/lead_qualification/application/profile_capture.py`) ya cumple esa función como servicio
  determinista; agregar un agente LLM encima duplicaría lógica ya cubierta por US-202 a US-205, US-208 y
  US-215 sin resolver ningún gap real.

### HUs paralelizables (Epic 4)

Análisis de dependencias reales del backlog pendiente (Epic 2 y 3 ya están implementadas — la
paralelización histórica de US-202 a US-205 se documenta en su nota INVEST, línea ~171 — por eso esta
sección cubre solo Epic 4, que es el trabajo por hacer). Una HU es "paralelizable" respecto a otra
cuando **no** aparece como su prerrequisito en la columna (d)/Alineación de ninguna HU del grupo.

#### Track A — Sin dependencias entre sí (se pueden asignar a agentes/devs distintos en simultáneo)

| HU | Por qué es independiente |
|----|---------------------------|
| US-212 | Wiring puro sobre servicios ya terminados (`AvailabilityValidatorService`/`SchedulingService`); no requiere ninguna otra HU de Epic 4. |
| AI-105 | Intent Router es un módulo nuevo aislado (clasificación LLM de 1 mensaje); se puede construir y testear con mensajes sintéticos sin esperar a AI-106 ni a ninguna HU de scheduling. |
| US-214 | Extiende `LeadScoringService` de forma aditiva; no depende de wiring de scheduling ni de prompts. |
| US-215 | Cambio de configuración (`profile_completeness_threshold`) sin dependencia de código nuevo. |
| US-216 | Reescritura de `DEFAULT_SYSTEM_PROMPT`; no depende de ninguna otra HU. |
| US-217 | Reordena extractores ya existentes de `qualification_flow.py`; no depende de US-215 aunque comparten motivación de negocio (recomendación temprana). |
| US-218 | Reordena el Identity Gate; solo requiere validar el contrato mínimo de wacrm, no otra HU de Epic 4. |
| US-219 | Nuevo extractor + columna nueva en `buyer_profiles`; aditivo, no depende de otras HUs. |

**Nota de conflicto de archivo (no es dependencia lógica, pero sí de merge):** US-216, US-217 y US-218
tocan `coordinator.py`/`prompts.py` en zonas cercanas (identity gate, orden de turnos, prompt system). Se
pueden desarrollar en paralelo, pero conviene coordinar el merge (branches cortos, rebase frecuente) para
evitar conflictos de texto, no de lógica.

**Nota de conflicto de migración:** US-214 y US-219 agregan columnas nuevas a `buyer_profiles`/`leads` en
paralelo. Son compatibles a nivel de dominio, pero sus migraciones Alembic deben generarse una después de
la otra (no simultáneamente) para evitar dos revisiones con el mismo `down_revision`.

#### Track B — Bloqueadas por una HU de Track A (empiezan cuando su prerrequisito está listo, no antes)

| HU | Bloqueada por | Qué habilita el prerrequisito |
|----|----------------|-------------------------------|
| US-213 | US-212 | Sin agendamiento real no existe `Appointment.scheduled_at` sobre el cual calcular 24h/2h. |
| AI-106 | AI-105 | El servicio RAG en sí (retrieval sobre KB) se puede prototipar en paralelo con Track A, pero el **wiring** que decide cuándo invocarlo (Objeción vs Q&A) necesita la categoría que produce el Intent Router. |
| US-220 | US-212 (débil) | El turno de profundización se puede redactar y testear en aislado, pero su siguiente paso natural (ofrecer horarios) no tiene efecto real hasta que exista agendamiento conectado — dependencia de producto, no de código. |
| US-221 | US-212 (fuerte) | No hay horarios reales que redactar en lenguaje natural sin el wiring de scheduling. |

**Regla de asignación:** todo Track A puede arrancar el mismo día, en paralelo, sin coordinación entre
HUs (solo la coordinación de archivo/migración ya señalada). Track B debe esperar a que su HU bloqueante
en Track A esté al menos integrada (no necesariamente en producción) antes de empezar su propia
implementación — no solo el diseño, que sí puede adelantarse.

---

## Archivos de referencia (no se modifican, solo se citan como fuente)

- `Documents/Oficial/Backlog.md`, `Maquina_Estados.md`, `Customer_Journey_Residencial_WhatsApp_Detallado.md`, `Agentic_System.md`, `AI_Recommendation_Domain_Model.md`
- `app/modules/lead_qualification/domain/models.py`, `application/completeness_gate.py`, `application/staleness_guard.py`, `application/profile_capture.py`, `infrastructure/lead_sync.py`
- `app/modules/recommendation/application/property_ingestion.py`, `retrieval.py`, `ranking_engine.py`, `explanation_generator.py`, `neighborhood_enrichment.py`, `recommendation_service.py`, `wiring.py`
- Epic 4: `app/modules/conversation_ownership/application/coordinator.py`, `link_guard.py`; `app/modules/conversation_ownership/domain/prompts.py`; `app/modules/conversation_ownership/infrastructure/llm_brain.py`; `app/modules/recommendation/application/search_diagnostics.py`; `app/modules/appointment/application/availability_validator.py`, `scheduling_service.py`, `reminder_port.py`; `app/modules/lead_qualification/application/lead_scoring.py`; `app/core/config.py`; `Documents/Oficial/Agentic_System.md` §12 (estado real verificado)

## Verificación

- El archivo `Documents/Oficial/HU_Calificacion_Recomendacion.md` debe existir con las secciones de
  arriba; revisar visualmente que cada HU cite nombres reales de clases/tablas/estados (no inventados)
  contrastando contra los paths listados en "Archivos de referencia".
- No se ejecuta código, no se corren tests, no se toca Supabase — es un entregable puramente documental.
