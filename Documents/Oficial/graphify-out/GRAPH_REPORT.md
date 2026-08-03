# Graph Report - .  (2026-07-21)

## Corpus Check
- Corpus is ~40,769 words - fits in a single context window. You may not need a graph.

## Summary
- 142 nodes · 165 edges · 13 communities (11 shown, 2 thin omitted)
- Extraction: 94% EXTRACTED · 5% INFERRED · 1% AMBIGUOUS · INFERRED: 8 edges (avg confidence: 0.86)
- Token cost: 0 input · 232,294 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Recommendation Domain Model|Recommendation Domain Model]]
- [[_COMMUNITY_Agentic System Design Components|Agentic System Design Components]]
- [[_COMMUNITY_Qualification & Recommendation User Stories|Qualification & Recommendation User Stories]]
- [[_COMMUNITY_Recommendation & Intelligence Modules|Recommendation & Intelligence Modules]]
- [[_COMMUNITY_Appointment & Post-Visit Epics|Appointment & Post-Visit Epics]]
- [[_COMMUNITY_Design Rationale & Doc Overviews|Design Rationale & Doc Overviews]]
- [[_COMMUNITY_CRM Sync & Lead Qualification Module|CRM Sync & Lead Qualification Module]]
- [[_COMMUNITY_Ownership & Handoff Governance|Ownership & Handoff Governance]]
- [[_COMMUNITY_State Machines & Customer Journey|State Machines & Customer Journey]]
- [[_COMMUNITY_Roadmap Sprints 0-1 & Deployment|Roadmap: Sprints 0-1 & Deployment]]
- [[_COMMUNITY_Roadmap Sprints 4-7|Roadmap: Sprints 4-7]]
- [[_COMMUNITY_Configuration Store|Configuration Store]]
- [[_COMMUNITY_Event Bus|Event Bus]]

## God Nodes (most connected - your core abstractions)
1. `Coordinator Agent` - 10 edges
2. `Seven Bounded Contexts (Modular Monolith)` - 8 edges
3. `HU — Appointment, Handoff & Ownership Policy Engine v1` - 8 edges
4. `HU — Qualification & Recommendation` - 7 edges
5. `US-404 — Materializar visita como Appointment (Scheduling Service)` - 6 edges
6. `Property (proposed table)` - 5 edges
7. `Blueprint Funcional Propuesto (Backlog)` - 5 edges
8. `Máquina de Estados (3 Tablas)` - 5 edges
9. `Conversation FSM (New→Greeting→Discovery→Recommendation→Scheduling→Waiting Response→Follow-up→Handoff)` - 5 edges
10. `Lead-to-Visit WhatsApp Agent — Agentic System Design` - 4 edges

## Surprising Connections (you probably didn't know these)
- `Appointment FSM (Requested→Pending→Confirmed→Rescheduled/Completed/Cancelled/No Show)` --semantically_similar_to--> `Module: Appointment (M5)`  [INFERRED] [semantically similar]
  Maquina_Estados.md → Architecture.md
- `Conversation FSM (New→Greeting→Discovery→Recommendation→Scheduling→Waiting Response→Follow-up→Handoff)` --semantically_similar_to--> `Conversation State Machine`  [INFERRED] [semantically similar]
  Maquina_Estados.md → Architecture.md
- `AI-104 — Appointment Suggestion (Backlog's Historias para IA)` --semantically_similar_to--> `AI-104 — Coordinator Agent y Intent Router LLM-backed [GAP]`  [AMBIGUOUS] [semantically similar]
  Backlog.md → HU_Calificacion_Recomendacion.md
- `US-404 — Materializar visita como Appointment (Scheduling Service)` --semantically_similar_to--> `Appointment FSM (Requested→Pending→Confirmed→Rescheduled/Completed/Cancelled/No Show)`  [INFERRED] [semantically similar]
  HU_Appointment_Handoff_Ownership.md → Maquina_Estados.md
- `Operational contract: wacrm pipeline stages must match closed PipelineStage enum (7 values)` --semantically_similar_to--> `wacrm stage-naming contract (closed PipelineStage enum vs free-text CRM stages)`  [INFERRED] [semantically similar]
  WACRM_API_Adaptation_Plan.md → Architecture.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Ownership Policy Engine spans design, architecture, and implementation HUs** — agentic_system_ownership_policy_engine, architecture_ownership_policy_engine, hu_appointment_handoff_ownership_us408 [INFERRED 0.85]
- **Recommendation pipeline: filter → semantic retrieval → ranking → explanation → enrichment** — architecture_structured_filter_service, architecture_semantic_retrieval_service, architecture_ranking_engine, architecture_explanation_generator, architecture_neighborhood_enrichment_adapter [EXTRACTED 1.00]
- **Three coordinated state machines: Conversation, Opportunity(CRM), Appointment** — maquina_estados_conversation_fsm, maquina_estados_opportunity_fsm, maquina_estados_appointment_fsm [EXTRACTED 1.00]

## Communities (13 total, 2 thin omitted)

### Community 0 - "Recommendation Domain Model"
Cohesion: 0.11
Nodes (19): Building (proposed table, out of Epic 2/3 scope), buyer_profiles (implemented, covers requirement_profile role), conversation_memory table, Lead (entity), Neighborhood / POI / Market Snapshot (out of scope), Property (proposed table), Property Listing (proposed table), Recommendation (proposed table) (+11 more)

### Community 1 - "Agentic System Design Components"
Cohesion: 0.12
Nodes (18): Availability Validator (not implemented), Coordinator Agent, Error-compounding chain rationale (deterministic services break LLM chain to raise success rate), GeminiGenerativeExtractor.extract (fallback qualification LLM), Guardrails Layer, Intent Router (not implemented), LangGraph framework selection, LangGraphResponder (single-node StateGraph, real code) (+10 more)

### Community 2 - "Qualification & Recommendation User Stories"
Cohesion: 0.12
Nodes (18): embedding (proposed polymorphic table), property_embeddings (implemented, covers embedding role), Epic 1 — Lead Intake (US-101), Epic 2 — Conversation Qualification (US-201), Epic 3 — Recommendation Engine (US-301), US-202 a US-205 — Captura de dimensiones del BuyerProfile (budget, location, property_type, timeline/must-haves), US-206 — Completeness Gate activation → ProfileCompleted, US-207 — Sync Opportunity Stage=Qualified a wacrm (+10 more)

### Community 3 - "Recommendation & Intelligence Modules"
Cohesion: 0.12
Nodes (17): Admin Gateway (CRUD versioned rollback), Seven Bounded Contexts (Modular Monolith), Conversation Mining Pipeline (batch ETL), Dashboard Query Service (CQRS read), Module: Engagement (M6), Explanation Generator (template + LLM redaction), Module: Intelligence & AI Admin (M7), Knowledge Graph Builder (incremental) (+9 more)

### Community 4 - "Appointment & Post-Visit Epics"
Cohesion: 0.12
Nodes (16): Module: Appointment (M5), Availability Validator (deterministic bottleneck), Google Calendar Adapter (conferenceData → Meet), Reminder Scheduler (24h/2h jobs), Scheduling Service (design), Epic 4 — Appointment Scheduling (US-401), Epic 5 — Visit, Epic 6 — Offer (+8 more)

### Community 5 - "Design Rationale & Doc Overviews"
Cohesion: 0.19
Nodes (15): ARSDA Scorecard rationale (4.15 — Scale with Caution, PMF not validated), Lead-to-Visit WhatsApp Agent — Agentic System Design, AI Broker Bounded Contexts (CRM, Inventory, Recommendation, Market Intelligence, AI Memory), Domain model design principles (JSONB evolution, decoupled embeddings, feedback loop), AI Recommendation Domain Model, Lead to Sales System — Architecture Document, Blueprint Funcional Propuesto (Backlog), Rationale: organize backlog by business capability, not by screen (+7 more)

### Community 6 - "CRM Sync & Lead Qualification Module"
Cohesion: 0.17
Nodes (13): Completeness Gate (Specification pattern), Conversation State Machine, Module: Lead & Qualification (M3), Lead Sync Adapter (ACL bidireccional wacrm), SoR discipline rationale (Conversation/Lead are projections, not masters), wacrm stage-naming contract (closed PipelineStage enum vs free-text CRM stages), Staleness Guard (isStale() 60s bound), OrganizationConfig.crm: CrmConfig (base_url, api_key, tenant_ref) (+5 more)

### Community 7 - "Ownership & Handoff Governance"
Cohesion: 0.22
Nodes (9): GuardrailInterceptor (implemented, regex synchronous), ownership_policy.py::OwnershipPolicyEngine (partial, scenarios 1 and 8 only), Module: Conversation & Ownership (M2), Handoff Package Builder (Facade), Outcome Listener (OwnershipOutcome capture), Ownership Policy Engine (Domain Service, E14), US-407 — Ensamblar Handoff Package antes de transferir, US-408 — Extender OPE con escenario 2 de la matriz E14 (+1 more)

### Community 8 - "State Machines & Customer Journey"
Cohesion: 0.53
Nodes (6): Estados CRM (New, Qualified, Visit, Negotiation, Won, Lost, Postventa), Happy Path (8 steps: recepción→confirmación), Appointment FSM (Requested→Pending→Confirmed→Rescheduled/Completed/Cancelled/No Show), Conversation FSM (New→Greeting→Discovery→Recommendation→Scheduling→Waiting Response→Follow-up→Handoff), Máquina de Estados (3 Tablas), Opportunity FSM (CRM) (New→Qualified→Visit→Negotiation→Won/Lost/Nurturing)

### Community 9 - "Roadmap: Sprints 0-1 & Deployment"
Cohesion: 0.40
Nodes (5): Deployment View (single-AZ MVP, activation triggers deferred), Rationale: deferred infra items activated only by measurable trigger (read replica, distributed lock, multi-AZ, Redis), Sprint 0 — Fundación, Sprint 1 — Núcleo Conversacional AI-first, Sprint 8 — Deployment View (cierre de QA-02)

### Community 10 - "Roadmap: Sprints 4-7"
Cohesion: 0.50
Nodes (4): Sprint 4 — Cierre del Flujo Operativo de Ventas (E6, E8, E14 v1), Sprint 5 — Engagement y Re-entrada Completa (E9, E14 v2), Sprint 6 — Administración de AI y Operabilidad (E12, E13 parcial), Sprint 7 — Inteligencia Continua (E10, E11, E13 cierre)

## Ambiguous Edges - Review These
- `Intent Router (not implemented)` → `LangGraphResponder (single-node StateGraph, real code)`  [AMBIGUOUS]
  Agentic_System.md · relation: conceptually_related_to
- `AI-104 — Appointment Suggestion (Backlog's Historias para IA)` → `AI-104 — Coordinator Agent y Intent Router LLM-backed [GAP]`  [AMBIGUOUS]
  Backlog.md · relation: semantically_similar_to

## Knowledge Gaps
- **36 isolated node(s):** `Lead (entity)`, `Building (proposed table, out of Epic 2/3 scope)`, `Neighborhood / POI / Market Snapshot (out of scope)`, `property_embeddings (implemented, covers embedding role)`, `AI Broker Bounded Contexts (CRM, Inventory, Recommendation, Market Intelligence, AI Memory)` (+31 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `Intent Router (not implemented)` and `LangGraphResponder (single-node StateGraph, real code)`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `AI-104 — Appointment Suggestion (Backlog's Historias para IA)` and `AI-104 — Coordinator Agent y Intent Router LLM-backed [GAP]`?**
  _Edge tagged AMBIGUOUS (relation: semantically_similar_to) - confidence is low._
- **Why does `Seven Bounded Contexts (Modular Monolith)` connect `Recommendation & Intelligence Modules` to `Appointment & Post-Visit Epics`, `Design Rationale & Doc Overviews`, `CRM Sync & Lead Qualification Module`, `Ownership & Handoff Governance`?**
  _High betweenness centrality (0.355) - this node is a cross-community bridge._
- **Why does `HU — Appointment, Handoff & Ownership Policy Engine v1` connect `Design Rationale & Doc Overviews` to `State Machines & Customer Journey`, `Roadmap: Sprints 4-7`?**
  _High betweenness centrality (0.347) - this node is a cross-community bridge._
- **Why does `Lead to Sales System — Architecture Document` connect `Design Rationale & Doc Overviews` to `Roadmap: Sprints 0-1 & Deployment`, `Recommendation & Intelligence Modules`?**
  _High betweenness centrality (0.237) - this node is a cross-community bridge._
- **What connects `Lead (entity)`, `Building (proposed table, out of Epic 2/3 scope)`, `Neighborhood / POI / Market Snapshot (out of scope)` to the rest of the system?**
  _47 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Recommendation Domain Model` be split into smaller, more focused modules?**
  _Cohesion score 0.1111111111111111 - nodes in this community are weakly interconnected._