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
  keyword/regex, sin LLM aún) ya llama a `BuyerProfileCaptureService.update_profile`; endpoint de
  soporte `POST /api/v1/leads/{lead_id}/profile/budget`. Falta el enrutamiento desde una conversación
  real (Coordinator Agent / AI-104) — ver
  `openspec/changes/qualification-dimensions-us-202-205/` y
  `openspec/specs/lead-qualification/us-202-205-enrichment.md`.
- (c) Tablas: `buyer_profiles`, `leads`.
- (d) Implementado hoy: `BuyerProfile.apply(patch)` en `lead_qualification/domain`.

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
  fijo de zonas conocidas, sin catálogo por-organización — abierto, ver design.md de este change);
  endpoint de soporte `POST /api/v1/leads/{lead_id}/profile/locations`. Falta enrutamiento desde
  conversación real (AI-104) — ver `openspec/changes/qualification-dimensions-us-202-205/`.
- (c) `buyer_profiles`.
- (d) Implementado: `BuyerProfile.locations: tuple[str]`.

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
  sinónimos en español, sin llamada LLM para el caso común); endpoint de soporte
  `POST /api/v1/leads/{lead_id}/profile/property-type`. Falta enrutamiento desde conversación real
  (AI-104) — ver `openspec/changes/qualification-dimensions-us-202-205/`.
- (c) `buyer_profiles`.
- (d) Implementado: `PropertyType` enum + `BuyerProfile.property_type`.

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
  `ProfilePatch` puede portar ambas dimensiones sin borrar la otra); endpoints de soporte
  `POST /api/v1/leads/{lead_id}/profile/timeline` y `.../must-haves`. Falta enrutamiento desde
  conversación real (AI-104) — ver `openspec/changes/qualification-dimensions-us-202-205/`.
- (c) `buyer_profiles`.
- (d) Implementado: `Timeline` enum, `must_haves: tuple[str]`.

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

### US-208 [GAP — no implementado] — Ampliar perfil a las 6 dimensiones del Customer Journey

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
- (c) `buyer_profiles` (requiere migración: columnas `financing_type`, `decision_maker_mode`).
- (d) [GAP] No existe en código; `PROFILE_DIMENSIONS = (budget, locations, property_type, timeline,
  must_haves)`.

### US-209 [GAP — no implementado] — Clasificación Hot/Warm/Cold y registro de objeciones

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
- (c) Tabla nueva propuesta: `lead_objections` (no existe en Supabase actual); `leads.lead_score` ya
  existe.
- (d) [GAP] No implementado. `Lead.lead_score` existe pero nada lo escribe desde objeciones.

### AI-102 [GAP — no implementado] — Extraer señales libres de la conversación hacia `conversation_memory`

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
- (b) Capa agentic: Requirement Extraction (`AI-102` en Backlog.md, solo título hasta ahora) —
  Qualification Flow / LLM. Cero código.
- (c) Tabla nueva `conversation_memory` (id, conversation_id, lead_id, memory_type, entity_name, value
  jsonb, confidence, created_at) — ya propuesta en `AI_Recommendation_Domain_Model.md`, no existe en
  Supabase.
- (d) [GAP] No implementado. Bloquea a US-211.

### US-211 [GAP — no implementado] — Agregar `conversation_memory` en `ai_profile` y `buyer_persona`

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
- (b) Capa agentic: sin dueño claro en Agentic_System.md hoy — encajaría como paso de síntesis dentro de
  Qualification Flow o como servicio propio; cero código.
- (c) Requiere columnas nuevas: `buyer_profiles.ai_profile` jsonb y `leads.buyer_persona` jsonb (ninguna
  existe hoy en Supabase ni en el ORM).
- (d) [GAP] No implementado. Depende de AI-102. Bloquea a que US-305 (Ranking) use una señal de afinidad
  real en vez de solo budget/zona/tipo.

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

### US-303 [GAP — parcial] — Filtrar candidatos duros por SQL en vez de Python

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
- (d) Implementado parcialmente: `StructuredFilterService.filter_candidates` +
  `candidate.matches_hard_filters()` — [GAP] falta reescribir a SQL.

### US-304 [GAP — parcial] — Migrar retrieval semántico a pgvector real

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
- (d) Implementado parcialmente: `SemanticRetrievalService.retrieve` en Python puro — [GAP] falta
  migración de esquema + query SQL.

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
- (c) Sin tabla propia hoy; candidata a `recommendations.neighborhood` (jsonb) en US-310.
- (d) Implementado: `NeighborhoodEnrichmentAdapter`, `GoogleMapsClient` — sin API key configurada
  (Sprint 3B), evento `NeighborhoodEnriched` ya modelado.

### US-308 [GAP — no implementado] — Reemplazar embedding stand-in por modelo real

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
- (d) [GAP] Hoy: `HashEmbeddingModel` (16-dim, stand-in). Bloquea a US-304.

### US-309 [GAP — no implementado] — Reconciliar esquema de `properties`

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
- (d) [GAP] No implementado; mismo hallazgo que `Documents/Oficial/plan-implementacion-tablas-supabase.md`
  (migración 0006, aún no escrita/aplicada).

### US-310 [GAP — no implementado] — Persistir RecommendationResult en tabla `recommendations`

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
- (d) [GAP] `RecommendationService.search()` existe pero el `RecommendationResult` nunca se persiste hoy.

### AI-104 [GAP — no implementado] — Coordinator Agent y Intent Router LLM-backed

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
- (b) Coordinator Agent + Intent Router — diseño puro en Agentic_System.md, cero código.
- (c) `ai_decision_traces` (tabla ya existe en Supabase, sin consumidor actual), `conversations`.
- (d) [GAP] No implementado; hoy la transición de estado y el disparo de `search()` se hacen
  directamente en `wiring.py` sin pasar por un Coordinator ni registrar trazas de decisión.

---

## Tabla resumen

| ID | Título breve | Estado FSM | Capa agentic | Tabla(s) | Implementado hoy |
|----|--------------|-----------|---------------|----------|-------------------|
| US-202 | Capturar presupuesto | Discovery (QUALIFICATION) | Qualification Flow (extractor + endpoint, sin enrutamiento conversacional — qualification-dimensions-us-202-205) | buyer_profiles | Parcial |
| US-203 | Capturar ubicación | Discovery (QUALIFICATION) | Qualification Flow (extractor + endpoint, sin enrutamiento conversacional — qualification-dimensions-us-202-205) | buyer_profiles | Parcial |
| US-204 | Capturar tipo de propiedad | Discovery (QUALIFICATION) | Qualification Flow (extractor + endpoint, sin enrutamiento conversacional — qualification-dimensions-us-202-205) | buyer_profiles | Parcial |
| US-205 | Capturar timeline y must-haves | Discovery (QUALIFICATION) | Qualification Flow (extractor + endpoint, sin enrutamiento conversacional — qualification-dimensions-us-202-205) | buyer_profiles | Parcial |
| US-206 | Completeness Gate | Discovery→Recommendation | Guardrail no-LLM | buyer_profiles, leads, outbox_events | Sí |
| US-207 | Sync Opportunity Stage=Qualified | Opportunity FSM (paralela) | Servicio determinista (ACL) | leads, crm_access_audit, crm_sync_cursors | Sí |
| US-208 | Ampliar a 6 dimensiones | Discovery (QUALIFICATION) | Qualification Flow (diseño) | buyer_profiles | No [GAP] |
| US-209 | Hot/Warm/Cold + objeciones | Transversal | Objection Handler (diseño) | lead_objections (nueva) | No [GAP] |
| AI-102 | Extraer señales libres a conversation_memory | Transversal (Discovery) | Requirement Extraction (diseño) | conversation_memory (nueva) | No [GAP] |
| US-211 | Agregar ai_profile / buyer_persona | Transversal | Sin dueño claro (diseño) | buyer_profiles.ai_profile, leads.buyer_persona (nuevas) | No [GAP] |
| US-302 | Ingestion de propiedades | Soporte previo a Recommendation | Matching Engine | properties, property_embeddings | Sí |
| US-303 | Filtro estructurado en SQL | Recommendation (RECOMMENDATION) | Matching Engine (SQL filters) | properties | Parcial |
| US-304 | Retrieval semántico pgvector | Recommendation (RECOMMENDATION) | Matching Engine (pgvector) | property_embeddings | Parcial |
| US-305 | Ranking ponderado | Recommendation (RECOMMENDATION) | Matching Engine | — (en memoria) | Sí |
| US-306 | Explicación en lenguaje natural | Recommendation (RECOMMENDATION) | Explanation (template, swap a LLM) | — (en memoria) | Sí |
| US-307 | Enriquecimiento de vecindario | Recommendation (RECOMMENDATION) | Servicio determinista fan-out/fan-in | — (en memoria) | Parcial |
| US-308 | Modelo de embeddings real | Soporte a Recommendation | Infraestructura | property_embeddings | No [GAP] |
| US-309 | Reconciliar esquema properties | Soporte a Recommendation | N/A (datos) | properties | No [GAP] |
| US-310 | Persistir recommendations | Recommendation (RECOMMENDATION) | Coordinator (orquesta, no existe aún) | recommendations (nueva) | No [GAP] |
| AI-104 | Coordinator Agent + Intent Router | Transversal a toda la Conversation FSM | Coordinator/Intent Router (diseño) | ai_decision_traces, conversations | No [GAP] |

## Archivos de referencia (no se modifican, solo se citan como fuente)

- `Documents/Oficial/Backlog.md`, `Maquina_Estados.md`, `Customer_Journey_Residencial_WhatsApp_Detallado.md`, `Agentic_System.md`, `AI_Recommendation_Domain_Model.md`
- `app/modules/lead_qualification/domain/models.py`, `application/completeness_gate.py`, `application/staleness_guard.py`, `application/profile_capture.py`, `infrastructure/lead_sync.py`
- `app/modules/recommendation/application/property_ingestion.py`, `retrieval.py`, `ranking_engine.py`, `explanation_generator.py`, `neighborhood_enrichment.py`, `recommendation_service.py`, `wiring.py`

## Verificación

- El archivo `Documents/Oficial/HU_Calificacion_Recomendacion.md` debe existir con las secciones de
  arriba; revisar visualmente que cada HU cite nombres reales de clases/tablas/estados (no inventados)
  contrastando contra los paths listados en "Archivos de referencia".
- No se ejecuta código, no se corren tests, no se toca Supabase — es un entregable puramente documental.
