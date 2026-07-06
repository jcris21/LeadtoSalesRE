# Graph Report - E:\FILES 2026\MVP_VIBECODE+AGENTIC\REALESTATE agentic Multichannel_Chat\Documents\Oficial  (2026-07-05)

## Corpus Check
- Corpus is ~21,769 words - fits in a single context window. You may not need a graph.

## Summary
- 78 nodes · 113 edges · 8 communities
- Extraction: 87% EXTRACTED · 13% INFERRED · 0% AMBIGUOUS · INFERRED: 15 edges (avg confidence: 0.91)
- Token cost: 176,459 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Ownership & Conversation Lifecycle|Ownership & Conversation Lifecycle]]
- [[_COMMUNITY_Coordinator & Scheduling Core|Coordinator & Scheduling Core]]
- [[_COMMUNITY_Learning & Recommendation Pipeline|Learning & Recommendation Pipeline]]
- [[_COMMUNITY_CRM & Data Synchronization|CRM & Data Synchronization]]
- [[_COMMUNITY_Guardrails & Tool Governance|Guardrails & Tool Governance]]
- [[_COMMUNITY_Lead Qualification Flow|Lead Qualification Flow]]
- [[_COMMUNITY_Source Documents|Source Documents]]
- [[_COMMUNITY_Multi-Tenancy & Deployment|Multi-Tenancy & Deployment]]

## God Nodes (most connected - your core abstractions)
1. `Coordinator Agent (SAS)` - 14 edges
2. `Coordinator Agent (LangGraph)` - 12 edges
3. `Conversation State Machine (persisted FSM)` - 11 edges
4. `Ownership Policy Engine (E14)` - 9 edges
5. `Ownership Policy Engine (Decision Table)` - 7 edges
6. `Guardrail Interceptor` - 5 edges
7. `Versioned Configuration Store` - 5 edges
8. `Guardrails Layer` - 4 edges
9. `Matching Engine (deterministic + RAG)` - 4 edges
10. `Ownership Policy Engine (rules)` - 4 edges

## Surprising Connections (you probably didn't know these)
- `Coordinator Agent (SAS)` --semantically_similar_to--> `Coordinator (AI module)`  [INFERRED] [semantically similar]
  Agentic_System.md → ArchitecturalDrivers.md
- `Hybrid Retrieval (SQL filters + pgvector)` --semantically_similar_to--> `Matching Engine (deterministic + RAG)`  [INFERRED] [semantically similar]
  Architecture.md → Agentic_System.md
- `Coordinator Agent (LangGraph)` --semantically_similar_to--> `Coordinator Agent (SAS)`  [INFERRED] [semantically similar]
  Architecture.md → Agentic_System.md
- `BuyerProfile Capture Service (progressive profiling)` --semantically_similar_to--> `Qualification Flow (Prompt Chaining)`  [INFERRED] [semantically similar]
  Architecture.md → Agentic_System.md
- `Guardrail Interceptor` --semantically_similar_to--> `Guardrails Layer`  [INFERRED] [semantically similar]
  Architecture.md → Agentic_System.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Deterministic non-LLM Services Extracted from the SAS** — agentic_system_matching_engine, agentic_system_availability_validator, agentic_system_scheduling_service, agentic_system_ownership_policy_engine [EXTRACTED 1.00]
- **Dormancy and Re-entry Ownership Flow** — architecture_reactivation_detector, architecture_reactivation_event, architecture_conversation_state_machine, architecture_ownership_policy_engine, architecture_ownership_decision, architecture_outcome_listener [EXTRACTED 1.00]
- **Explainable Recommendation Pipeline** — architecture_hybrid_retrieval, architecture_ranking_engine, architecture_explanation_generator, architecture_neighborhood_enrichment_adapter [EXTRACTED 1.00]

## Communities (8 total, 0 thin omitted)

### Community 0 - "Ownership & Conversation Lifecycle"
Cohesion: 0.18
Nodes (18): Ownership Policy Engine (rules), Conversation State Machine (15 CRM states), Broker-Request Guardrail (Scenario 8), Conversation Lifecycle (dormancy and re-entry), Coordinator (AI module), Human Handoff Mechanics (E8), Ownership Policy Engine (E14), QA-09 Ownership Reliability (+10 more)

### Community 1 - "Coordinator & Scheduling Core"
Cohesion: 0.17
Nodes (16): AIDecisionTrace (per-decision tracing), Availability Validator, BuyerProfile, Coordinator Agent (SAS), Eval Pipeline (10 QA cases in CI/CD), LangGraph Framework Recommendation, Matching Engine (deterministic + RAG), Objection Handler (LLM+RAG) (+8 more)

### Community 2 - "Learning & Recommendation Pipeline"
Cohesion: 0.18
Nodes (11): Continuous Learning Loop, Prompt Registry (versioned, per organization), Recommendation Engine (E4), Conversation Mining Pipeline (batch ETL), Explanation Generator, Hybrid Retrieval (SQL filters + pgvector), Knowledge Graph Builder (incremental), Market Insight Discovery Service (+3 more)

### Community 3 - "CRM & Data Synchronization"
Cohesion: 0.24
Nodes (10): Chatwoot (SoR: conversations), CRM Synchronization (E7), Data Ownership (System of Record), QA-13 Data Consistency (60s staleness bound), Supabase (SoR: AI domain), wacrm (SoR: leads and pipeline), Chatwoot Webhook Adapter (ACL), Event Bus (Transactional Outbox/Inbox) (+2 more)

### Community 4 - "Guardrails & Tool Governance"
Cohesion: 0.22
Nodes (9): AI Sidebar (Chatwoot), Autonomy Matrix (Risk × Complexity), Guardrails Layer, Typed Tool Contracts (9 tools), Admin Gateway (versioned CRUD + RBAC), Versioned Configuration Store, Guardrail Configuration Service, Guardrail Interceptor (+1 more)

### Community 5 - "Lead Qualification Flow"
Cohesion: 0.25
Nodes (8): ARSDA Scorecard (4.15 — Scale with Caution), Error Compounding Mitigation, Intent Router, Qualification Flow (Prompt Chaining), SAS + Deterministic Services Hybrid Decision, QA-14 Qualification Quality (completeness gate), BuyerProfile Capture Service (progressive profiling), Completeness Gate (Specification pattern)

### Community 6 - "Source Documents"
Cohesion: 0.67
Nodes (3): Lead-to-Visit WhatsApp Agent — Agentic System Design, ArchitecturalDrivers.md v0.2 — AI-Native Real Estate Lead Qualification Platform, Lead to Sales System — Architecture Document

### Community 7 - "Multi-Tenancy & Deployment"
Cohesion: 0.67
Nodes (3): Modular Monolith Constraint, QA-03 Organization-Ready Scalability, Row-Level Security by organization_id

## Knowledge Gaps
- **15 isolated node(s):** `Lead-to-Visit WhatsApp Agent — Agentic System Design`, `Objection Handler (LLM+RAG)`, `Eval Pipeline (10 QA cases in CI/CD)`, `AI Sidebar (Chatwoot)`, `Supabase (SoR: AI domain)` (+10 more)
  These have ≤1 connection - possible missing edges or undocumented components.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Coordinator Agent (LangGraph)` connect `Coordinator & Scheduling Core` to `Ownership & Conversation Lifecycle`, `Learning & Recommendation Pipeline`, `CRM & Data Synchronization`, `Guardrails & Tool Governance`, `Lead Qualification Flow`?**
  _High betweenness centrality (0.414) - this node is a cross-community bridge._
- **Why does `Coordinator Agent (SAS)` connect `Coordinator & Scheduling Core` to `Ownership & Conversation Lifecycle`, `Guardrails & Tool Governance`, `Lead Qualification Flow`?**
  _High betweenness centrality (0.262) - this node is a cross-community bridge._
- **Why does `Conversation State Machine (persisted FSM)` connect `Ownership & Conversation Lifecycle` to `Coordinator & Scheduling Core`, `Lead Qualification Flow`?**
  _High betweenness centrality (0.214) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `Coordinator Agent (SAS)` (e.g. with `Coordinator (AI module)` and `Coordinator Agent (LangGraph)`) actually correct?**
  _`Coordinator Agent (SAS)` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `Coordinator Agent (LangGraph)` (e.g. with `LangGraph Framework Recommendation` and `Coordinator Agent (SAS)`) actually correct?**
  _`Coordinator Agent (LangGraph)` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Lead-to-Visit WhatsApp Agent — Agentic System Design`, `Objection Handler (LLM+RAG)`, `Autonomy Matrix (Risk × Complexity)` to the rest of the system?**
  _18 weakly-connected nodes found - possible documentation gaps or missing edges._