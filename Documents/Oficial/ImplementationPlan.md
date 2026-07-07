# ImplementationPlan.md

# Lead to Sales System — Plan de Implementación por Sprints

**Propósito:** traducir el diseño ya instanciado en **Architecture.md** (9 iteraciones ADD, componentes, puertos, diagramas de secuencia y decisiones registradas en §10) en un plan de construcción ejecutable. Este documento **no re-diseña nada** — cada sprint referencia los elementos concretos (componentes de §6, puertos de §8, secuencias de §7) que ya fueron decididos, y su Definition of Done cita los QA scenarios que el Paso 7 de cada iteración marcó como objetivo.

**Relación con los demás documentos:** ArchitecturalDrivers.md define *qué* debe lograr el sistema (épicas, QA scenarios, prioridad de negocio); IterationPlan.md definió *en qué orden se diseñó*; Architecture.md es la fuente de verdad de *qué construir*; este documento define *en qué orden construirlo* y *cómo saber que cada sprint está terminado*.

**Nota de reconciliación:** el roadmap original en ArchitecturalDrivers.md §7 (Sprints 0–8, escrito antes de ejecutar el proceso ADD) queda **superado por este plan**, que refleja los componentes reales instanciados — incluyendo la Iteración 9 (Deployment View) que no existía en el roadmap original, y la distribución real del Ownership Policy Engine a través de tres sprints (no uno solo, como se estimaba inicialmente).

---

## Sprint 0 — Fundación (Epic: ninguna de negocio; fundacional)

**Objetivo:** levantar la infraestructura que todos los demás sprints dan por sentada.

| Elemento a construir | Referencia en Architecture.md |
|---|---|
| Modular Monolith en FastAPI, 7 módulos con límites Ports & Adapters | §5 Container Diagram |
| Supabase (Postgres + pgvector) con RLS por `organization_id` | §5, §10 (Iter. 1) |
| Transactional Outbox/Inbox + worker de publicación | §7.2, `EventBusPort` (§8) |
| OpenTelemetry + tabla `AIDecisionTrace` | §7.3, `TracePort` (§8) |
| Versioned Configuration Store (`OrganizationConfig`, `PromptTemplate/Version`) | §7.1, `ConfigStorePort` (§8) |
| Middleware de resolución de `organizationId` | §7.1 |

**Definition of Done:** CON-1–CON-8, QA-03, QA-05, QA-07, CRN-3 (mecanismo), CRN-9, CRN-10 → **Satisfied** (ver análisis Paso 7, Iteración 1). Prueba de aceptación: crear una segunda organización de prueba solo con datos de configuración, sin cambios de código ni deploy.

**Dependencias:** ninguna (greenfield).

---

## Sprint 1 — Núcleo Conversacional AI-first (Epic: E1, E2, E14-skeleton)

| Elemento a construir | Referencia |
|---|---|
| Chatwoot Webhook Adapter (ACL) | §6.1, `ChatwootWebhookPort` |
| Conversation State Machine (estados completos incl. Dormant/Reactivated) | §6.1, `ConversationStateMachinePort` |
| Coordinator Agent sobre LangGraph con checkpoints | §6.1 |
| Guardrail Interceptor (hardcodeado en esta etapa; se configura en Sprint 6) | §7.5, `GuardrailPort` |
| Ownership Policy Engine — solo escenarios 1 y 8 | §6.1.1, `OwnershipPolicyEnginePort` |
| Ack inmediato + procesamiento asíncrono | §7.4 |

**Definition of Done:** E1, E2 → **Satisfied**; E14-skeleton, QA-01, QA-09, QA-06 → **Satisfied**; QA-02 → **Partially satisfied** (tolerancia a fallos de proceso; la meta 99% cierra en Sprint 8). CRN-5 → arranca (Not satisfied → primeras tools).

**Dependencias:** Sprint 0 (Config Store, Event Bus, RLS).

---

## Sprint 2 — Calificación y Datos Confiables (Epic: E3, E7)

| Elemento a construir | Referencia |
|---|---|
| Lead Sync Adapter (CDC por polling + cursor) hacia wacrm | §6.2, `LeadSyncPort` |
| BuyerProfile Capture Service (progressive profiling) | §6.2, `BuyerProfileCapturePort` |
| Completeness Gate | §7.8, `CompletenessGatePort` |
| Staleness Guard | §7.9, `StalenessGuardPort` |
| RBAC/audit centralizado en el Adapter (modelo de roles se especifica en Sprint 6) | §6.2 |

**Definition of Done:** E3, E7, QA-13, QA-14 → **Satisfied**; QA-08 → **Partially satisfied** (mecanismo listo, roles concretos en Sprint 6). Prueba de aceptación: ninguna decisión de negocio se ejecuta con `Lead.isStale() = true` sin forzar re-sync primero.

**Dependencias:** Sprint 1 (Coordinator con nodo extensible).

---

## Sprint 3 — Motor de Recomendación Explicable (Epic: E4, E5)

| Elemento a construir | Referencia |
|---|---|
| Property Ingestion Pipeline (embeddings precalculados) | §6.3 |
| Structured Filter Service + Semantic Retrieval Service (Hybrid Retrieval) | §6.3, §7.10 |
| Ranking Engine (RankingSignals, sin LLM) | §6.3, `RankingEnginePort` |
| Explanation Generator | §7.11, `ExplanationPort` |
| Neighborhood Enrichment Adapter (fan-out/fan-in + timeout/fallback) | §7.10, §7.12, `NeighborhoodEnrichmentPort` |

**Definition of Done:** E4, E5, QA-10, QA-11 → **Satisfied**; QA-01 (recomendación completa <15s) → **Satisfied**, verificado con prueba de carga sobre el flujo de §7.10. CRN-5 avanza (tools de recomendación orquestadas).

**Dependencias:** Sprint 2 (perfil completo como precondición de búsqueda).

---

## Sprint 4 — Cierre del Flujo Operativo de Ventas (Epic: E6, E8, E14 v1)

| Elemento a construir | Referencia |
|---|---|
| Availability Validator | §7.13, `AvailabilityValidatorPort` |
| Google Calendar Adapter (`conferenceData.createRequest` → Meet) | §7.13, `GoogleCalendarPort` |
| Scheduling Service + Reminder Scheduler (24h/2h) | §7.13, §7.14 |
| Handoff Package Builder | §7.15, `HandoffPackagePort` |
| Ownership Policy Engine — escenario 2 agregado | §7.16 |
| Outcome Listener (captura `OwnershipOutcome`) | §7.16, `OutcomeListenerPort` |

**Definition of Done:** E6, E8, E14 v1, QA-09, QA-11, CRN-4 → **Satisfied**. CRN-5 → **cierra** (orquestación completa de tools del happy path). **Prueba de aceptación crítica:** ningún test de agendamiento pasa si `Avail` devuelve `unavailable` — validar explícitamente el riesgo crítico de negocio del customer journey.

**Dependencias:** Sprint 3 (Top-3 recomendado antes de poder agendar visita sobre él).

---

## Sprint 5 — Engagement y Re-entrada Completa (Epic: E9, E14 v2)

| Elemento a construir | Referencia |
|---|---|
| Follow-up Scheduler | §6.5, `FollowUpSchedulerPort` |
| Campaign Dispatcher | §6.5, `CampaignDispatcherPort` |
| Reactivation Detector | §7.17, `ReactivationDetectorPort` |
| Ownership Policy Engine — Decision Table completa (10 escenarios, prioridad) | §6.1.2, §7.19 |
| `OwnershipPolicy` configurable por organización (dato, aún sin UI) | §8 (Iter. 6) |

**Definition of Done:** E9, E14 (matriz completa) → **Satisfied**; QA-09, CRN-1, CRN-2 → **Satisfied**. **Prueba de aceptación:** property-based tests confirmando que exactamente una regla gana para cada combinación relevante de contexto (§7.19); ni Follow-up ni Campaign invocan al OPE directamente.

**Dependencias:** Sprint 4 (Handoff y escenario 2 ya existentes, se extienden aquí).

---

## Sprint 6 — Administración de AI y Operabilidad (Epic: E12, E13 parcial)

| Elemento a construir | Referencia |
|---|---|
| Admin Gateway (CRUD versionado con rollback) | §6.6, `AdminGatewayPort` |
| RBAC Check — 4 roles por organización (cierra QA-08) | §7.20, `RBACPort` |
| Tool Registry | §6.6, `ToolRegistryPort` |
| Guardrail Configuration Service (reemplaza reglas hardcodeadas del Sprint 1) | §7.21, `GuardrailConfigPort` |
| Dashboard Query Service — KPIs operativos | §7.22, `DashboardQueryPort` |

**Definition of Done:** E12, QA-08 (cierre), QA-07 (consulta) → **Satisfied**. E13 alcanzado parcialmente (KPIs operativos; Market Intelligence en Sprint 7).

**Dependencias:** Sprints 1–5 (administra configuración ya en uso desde entonces).

---

## Sprint 7 — Inteligencia Continua (Epic: E10, E11, E13 cierre)

| Elemento a construir | Referencia |
|---|---|
| Meet Transcript Adapter (opt-in `transcriptSource`, cierra CON-8) | §7.23, `MeetTranscriptPort` |
| Conversation Mining Pipeline (batch ETL) | §7.24, `ConversationMiningPort` |
| Knowledge Graph Builder (incremental, por eventos) | §7.24, `KnowledgeGraphPort` |
| Market Insight Discovery Service (con provenance obligatoria) | §7.25, `MarketInsightPort` |
| Segmentation Dashboard (extiende Dashboard Query Service) | §7.25, `SegmentationDashboardPort` |

**Definition of Done:** E10, E11, E13 (cierre completo), QA-12, CRN-7, CON-8 (cierre final) → **Satisfied**. **Prueba de aceptación:** ningún `MarketInsight` se aplica a un prompt o `RankingSignal` sin provenance verificable y aprobación vía Admin Gateway.

**Dependencias:** Sprint 6 (Admin Gateway para aprobar ajustes de prompt); `MessageRef` acumulado desde Sprint 1.

---

## Sprint 8 — Deployment View (cierre de QA-02)

**Nota:** este sprint es transversal a la infraestructura, no a un módulo de dominio — puede ejecutarse en paralelo desde Sprint 1 si el equipo lo permite, pero se valida formalmente aquí antes de producción.

| Elemento a construir | Referencia |
|---|---|
| ≥2 réplicas stateless detrás de Load Balancer, single-AZ | §5.1 |
| Health checks `/healthz`, `/readyz` | §7.26, §8 |
| Outbox Worker single-writer con auto-restart | §5.1 |
| Backups automáticos + PITR (en vez de multi-AZ en el MVP) | §5.1 |

**Definition of Done:** QA-02 → **Satisfied**. Prueba de aceptación: deploy sin downtime (§7.27) y failover ante caída simulada de una réplica (§7.26), verificado en ambiente de staging antes del primer despliegue a producción.

**Dependencias:** Sprint 1 (requiere que el estado ya viva en Postgres, no en el proceso).

---

## Resumen de trazabilidad

| Sprint | Epics cerradas | QA scenarios que cierran aquí |
|---|---|---|
| 0 | — (fundación) | QA-03, QA-05, QA-07 |
| 1 | E1, E2 | QA-01, QA-09, QA-06 |
| 2 | E3, E7 | QA-13, QA-14 |
| 3 | E4, E5 | QA-10, QA-11 |
| 4 | E6, E8, E14 v1 | (riesgo crítico de negocio) |
| 5 | E9, E14 completo | CRN-1, CRN-2 |
| 6 | E12, E13 parcial | QA-08 |
| 7 | E10, E11, E13 completo | QA-12, CON-8 |
| 8 | — (infraestructura) | QA-02 |

**Ítems explícitamente diferidos, no parte de ningún sprint del MVP** (activar solo por disparador medible, ver Architecture.md §5.1 y la conversación de Redis): Postgres read replica, Outbox Worker con lock distribuido, Multi-AZ, Redis (cache/lock/rate-limiting). Cada uno con su disparador de activación ya documentado — no se planifican por fecha, se activan por evidencia.

## Consideraciones de secuenciación para el equipo

- Sprints 0–4 son estrictamente secuenciales (cada uno depende del anterior para su precondición de negocio: sin perfil completo no hay recomendación; sin recomendación no hay cita).
- Sprints 5–7 pueden solaparse parcialmente con backlog de otro desarrollador si el equipo lo permite, ya que actúan sobre módulos ya estables (M2 extendido, M7 nuevo) sin tocar M3/M4/M5.
- Sprint 8 (Deployment) es candidato a ejecutarse en paralelo desde el inicio (infraestructura base) aunque su *validación formal* como Definition of Done ocurra al final, antes de producción.
