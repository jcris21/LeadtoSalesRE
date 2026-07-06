# AI Workspace Integration with Chatwoot (ADR-002)

## Decision

Chatwoot will remain the **Conversation Hub**. It will **not** become the AI platform.

All Agentic AI logic, configuration and orchestration will live in the **FastAPI AI Core**.

Only lightweight UI extensions will be added to Chatwoot to provide contextual information to human agents.

---

# Chatwoot AI Sidebar

Each conversation should display an **AI Sidebar** containing:

## Lead Information

- AI / Human ownership status
- Active AI Agent
- Conversation status
- CRM stage
- Lead Score
- Qualification progress
- Channel origin (WhatsApp, Instagram, etc.)
- Last CRM synchronization

---

## Recommendation Summary

- Top 3 recommended properties
- Buyer profile summary
- Main buying motivations
- Objections detected
- Next Best Action

---

## Timeline

```
Lead Created

↓

Qualification

↓

Recommendation

↓

Appointment

↓

Follow-up

↓

Human Handoff
```

---

## Actions

- Take Over Conversation
- Return Conversation to AI
- Force Requalification
- Schedule Appointment
- View CRM Record

---

# Prompt & AI Configuration

Prompt management **will NOT be implemented inside Chatwoot**.

Instead, FastAPI will expose an independent **AI Admin Console**.

Each AI Agent will have configurable:

- System Prompt
- Default Template
- Prompt Variables
- Model Selection
- Temperature
- Tool Selection (MCP / APIs)
- Guardrails
- Version History
- Rollback
- Evaluation Metrics

This allows prompt engineering without modifying Chatwoot.

---

# Minimal Chatwoot Customization

Only lightweight frontend extensions are recommended:

- AI Sidebar
- AI/Human status badge
- CRM status badge
- Active AI Agent indicator
- Recommendation card
- Timeline visualization

No business logic or AI orchestration should reside inside Chatwoot.

---

# Recommended Architecture

```text
                    Chatwoot
             (Conversation Platform)

        +--------------------------------+
        | Customer Conversation          |
        | Human Agent Workspace          |
        | AI Sidebar (Context Only)      |
        +--------------------------------+
                     │
             REST API / Webhooks
                     │
                     ▼
          +----------------------------+
          |      FastAPI AI Core       |
          | Modular Monolith (DDD)     |
          +----------------------------+
          | Coordinator Agent          |
          | Qualification Agent        |
          | Recommendation Agent       |
          | Neighborhood Agent         |
          | Calendar Agent             |
          | CRM Agent                  |
          | Follow-up Agent            |
          +----------------------------+
                     │
     ┌───────────────┼──────────────────────┐
     ▼               ▼                      ▼
 Supabase       OpenAI / Gemini      Google Maps MCP
(Postgres +      LLM + Embeddings    Places Intelligence
 pgvector)                             & Nearby Search
                     │
                     ▼
                 Google Calendar
                     │
                     ▼
                   wacrm CRM
```

---

# Benefits

- Clear separation of concerns.
- Chatwoot remains upgradeable without maintaining a fork.
- AI platform evolves independently.
- Full Python AI ecosystem (FastAPI, LangGraph, ADK, MCP, RAG).
- DDD-compliant architecture.
- Future-ready for multi-agent systems and microservices.
- Reusable AI Core independent of the conversation platform.