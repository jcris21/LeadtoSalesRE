# AI-Native Real Estate Lead Qualification & Auto-Appointment Platform
## MVP Architecture Plan (Monolithic Modular + Agentic AI)

**Role:** CTO
**Architecture Style:** Modular Monolith
**Domain:** Real Estate Lead Qualification
**Target:** Validate Product Market Fit before Microservices

---

# 1. Product Vision

Construir una plataforma Agentic AI que permita a agencias inmobiliarias automatizar completamente el proceso de:

Lead →
Qualification →
Recommendation →
Appointment →
CRM →
Human Hand-off

El agente humano únicamente interviene cuando:

- Lead está calificado
- Existe alta intención de compra
- Existe cita agendada

Todo lo demás será realizado por agentes AI.

---

# 2. North Star Metric

Qualified Appointment Rate

```
Qualified Meetings /
Incoming Leads
```

Secondary Metrics

- Lead Response Time
- Qualification Completion Rate
- Recommendation CTR
- Calendar Booking Rate
- Cost per Qualified Lead
- Human Intervention Rate
- Follow-up Completion Rate
- Property Match Accuracy
- Lead Conversion Rate

---

# 3. MVP Scope

## Included

✅ WhatsApp Business

✅ Instagram DM

✅ Chatwoot Inbox

✅ CRM

https://github.com/ArnasDon/wacrm

✅ Google Calendar

✅ Supabase

- PostgreSQL
- pgvector
- Storage

✅ OpenAI

- Responses API
- Embeddings

✅ RAG

✅ Recommendation Engine

✅ Agentic Workflow

---

# NOT Included

Voice

Email

SMS

MLS integrations

Mortgage APIs

Payments

ERP

---

# 4. Architectural Principles

## DDD

Each bounded context owns:

- Models
- Services
- Events
- Repository
- Policies

No shared business logic.

---

## DDIA

Designing Data Intensive Applications

Principles

- Event-driven
- Immutable events
- Idempotency
- Eventually consistent
- CQRS ready
- Async processing

---

## ADD (Attribute Driven Design)

Architectural Drivers

### Performance

Lead response

<3 seconds

---

### Availability

99%

---

### Scalability

100 agencies

50k conversations

---

### Maintainability

Modular

---

### Observability

Tracing

Logging

Metrics

---

### Security

JWT

RBAC

Audit Logs

Encryption

---

# 5. Modular Monolith

```
apps/

    api

modules/

    communication

    lead

    recommendation

    qualification

    property

    appointment

    crm

    workflow

    rag

    ai

    notification

    analytics

shared/

    auth

    events

    database

    observability
```

---

# 6. Bounded Contexts

---

## Communication

Responsibility

Receive messages

Supported channels

- WhatsApp
- Instagram
- Chatwoot

Entities

Conversation

Message

Channel

Events

MessageReceived

ConversationStarted

---

## Lead

Entities

Lead

BuyerProfile

LeadScore

Events

LeadCreated

LeadUpdated

LeadQualified

---

## Qualification

Goal

Collect buying information.

Questions

Location

Budget

Mortgage

Agent

Timeline

Property Type

Bedrooms

Bathrooms

Amenities

Move-in Date

Children

Pets

Parking

Remote Work

Schools

Events

QualificationStarted

QualificationCompleted

---

## Recommendation

Goal

Return Top 3 properties.

Sources

Transactional DB

+

Vector Search

Responsibilities

Ranking

Filtering

Similarity

Personalization

Output

Top 3

Arguments

Persuasive explanation

---

## Property

Source

Supabase

Entities

Property

Listing

Developer

Neighborhood

Availability

---

## Appointment

Responsibilities

Calendar

Availability

Booking

Reschedule

Cancellation

Google Calendar

Events

AppointmentCreated

AppointmentConfirmed

AppointmentCancelled

---

## CRM

Responsibilities

Pipeline

Stages

Notes

Tasks

Sync

Integration

wacrm

---

## Workflow

Responsibilities

Follow-up

Automation

Retries

Escalations

Timers

---

## Notification

Channels

Slack

Email

Push

Chatwoot

Human handoff

---

## Analytics

KPIs

Funnels

Dashboards

Conversion

---

# 7. Agentic System

```
Coordinator Agent

        │

        ├── Qualification Agent

        ├── Recommendation Agent

        ├── Negotiation Agent

        ├── Calendar Agent

        ├── CRM Agent

        └── Follow-up Agent
```

Coordinator orchestrates.

Workers execute.

---

# 8. AI Agents

## Qualification Agent

Goal

Extract structured information.

Output

```json
{
 location:"",
 budget:"",
 mortgage":"",
 timeline":""
}
```

---

## Recommendation Agent

Inputs

Buyer Profile

+

Property DB

+

RAG

Output

Top 3

Reasons

Confidence

---

## Negotiation Agent

Responsibilities

Handle objections

Persuasion

FAQ

Closing

---

## Calendar Agent

Responsibilities

Find availability

Book

Reschedule

Confirm

Google Calendar

---

## CRM Agent

Responsibilities

Update stages

Notes

Activities

Owner

---

## Follow-up Agent

Responsibilities

Recontact

Nurturing

Escalation

Timers

---

# 9. State Machine

```
NEW

↓

CONTACTED

↓

QUALIFYING

↓

QUALIFIED

↓

RECOMMENDATION

↓

APPOINTMENT

↓

HANDED_OFF

↓

VISIT

↓

NEGOTIATION

↓

SOLD

or

LOST
```

---

# 10. Recommendation Engine

Inputs

Lead Profile

+

Property DB

+

Embeddings

Ranking

```
Score

=

0.35 Similarity

+

0.25 Budget Match

+

0.20 Location Match

+

0.10 Timeline

+

0.10 Amenities
```

Returns

Top 3

Confidence

---

# 11. RAG

Knowledge

Property descriptions

Amenities

Neighborhoods

Schools

HOA

Transportation

Developer reputation

Financing

FAQ

Buying process

Documents

Embeddings

OpenAI

Stored in

pgvector

---

# 12. Follow-up Engine

Examples

```
After 1 day

↓

New recommendation

↓

After 3 days

↓

Price update

↓

After 7 days

↓

Availability reminder

↓

After 14 days

↓

Limited offer

↓

No response

↓

Human handoff
```

---

# 13. Human Handoff

Triggers

Appointment booked

Low confidence

High value lead

Angry customer

Escalation request

Complex financing

Human receives

Conversation

Summary

Buyer Profile

Top Properties

Appointment

CRM History

---

# 14. Event Bus

Events

MessageReceived

↓

LeadCreated

↓

QualificationCompleted

↓

RecommendationGenerated

↓

AppointmentBooked

↓

CRMUpdated

↓

FollowupScheduled

↓

LeadAssigned

---

# 15. Database

Supabase

Tables

```
leads

buyer_profiles

properties

property_embeddings

appointments

conversations

messages

crm_sync

followups

events
```

---

# 16. External Integrations

Chatwoot

↓

Webhook

↓

Communication Module

↓

Agent System

↓

CRM

↓

Google Calendar

↓

Supabase

↓

OpenAI

---

# 17. Folder Structure

```
src/

 modules/

     communication/

     lead/

     qualification/

     recommendation/

     property/

     appointment/

     crm/

     rag/

     ai/

     workflow/

     analytics/

 shared/

 infrastructure/

 tests/
```

---

# 18. Technology Stack

Backend

- NestJS
- TypeScript

Database

- Supabase
- PostgreSQL
- pgvector

Messaging

- Chatwoot

CRM

- wacrm

AI

- OpenAI Responses API
- Embeddings

Workflow

- Temporal (future)
- Trigger.dev (MVP) o BullMQ

Search

- PostgreSQL Full Text
- pgvector

Monitoring

- OpenTelemetry
- Grafana
- Loki

Deployment

- Docker
- Coolify
- Railway
- DigitalOcean

---

# 19. Evolution Roadmap

## Phase 1

Monolithic Modular

Single Database

Sync + Async

One deployment

---

## Phase 2

Extract

AI Module

Workflow Module

Recommendation Module

---

## Phase 3

Event Bus

Kafka

NATS

Redis Streams

---

## Phase 4

Microservices

Communication

Recommendation

CRM

Appointment

Analytics

independent deployments

---

# 20. MVP Success Criteria

- < 5 segundos para responder el primer mensaje.
- > 80% de conversaciones calificadas automáticamente.
- > 60% de leads con perfil completo.
- > 50% de recomendaciones aceptadas (clic o interés).
- > 35% de leads calificados convierten en cita.
- > 90% de sincronización exitosa con CRM.
- < 15% de conversaciones requieren intervención humana antes de la calificación.
- Reducción > 70% del tiempo operativo invertido por agentes en tareas repetitivas.

---

# 21. Future AI Capabilities

- Multi-agent planner con memoria persistente.
- Aprendizaje continuo a partir de conversaciones exitosas.
- Personalización mediante preferencias históricas del cliente.
- Scoring predictivo de probabilidad de cierre.
- Generación automática de argumentos de venta según perfil psicográfico.
- Optimización dinámica de follow-ups mediante experimentación (A/B testing).
- Detección de intención de compra y urgencia usando modelos de clasificación.
- Recomendaciones híbridas (contenido + colaborativo + vectorial + reglas).
- Voice AI (WhatsApp Voice / llamadas).
- Agente de negociación hipotecaria e integración con entidades financieras.
- Dashboard de inteligencia comercial con métricas de conversión, cohortes y atribución.


# Aclaración Arquitectónica: Chatwoot como Plataforma Conversacional y FastAPI como Core Agentic

> **Decisión de arquitectura (ADR-001):** La plataforma adopta una **arquitectura de composición**, donde **Chatwoot NO será modificado ni extendido con lógica de negocio o IA**. Toda la inteligencia del sistema residirá en un backend independiente desarrollado en **FastAPI (Python)**.

---

# Principios de Diseño

## Single Responsibility

Cada plataforma debe enfocarse únicamente en aquello para lo que fue diseñada.

| Plataforma | Responsabilidad |
|------------|-----------------|
| **Chatwoot** | Omnicanalidad, conversaciones, agentes humanos, inbox, notificaciones, WebSockets |
| **FastAPI AI Core** | Lógica de negocio, DDD, agentes IA, RAG, Recommendation Engine, Calendar, CRM, Workflow |

Esto evita acoplamiento innecesario y facilita la evolución independiente de cada componente.

---

# Rol de Chatwoot

Chatwoot funcionará exclusivamente como **Customer Communication Hub**.

Sus responsabilidades incluyen:

- Recepción de mensajes desde WhatsApp Business
- Recepción de mensajes desde Instagram (Meta)
- Gestión de conversaciones
- Gestión de agentes humanos
- Bandejas de entrada (Inbox)
- Etiquetas (Labels)
- Notas internas
- Asignación de conversaciones
- WebSockets y tiempo real
- API REST
- Webhooks
- Gestión de usuarios y permisos

No contendrá:

- lógica de IA
- prompts
- RAG
- Recommendation Engine
- memoria conversacional
- workflows de negocio
- calendar scheduling
- lead qualification
- CRM orchestration

---

# Rol de FastAPI

FastAPI implementará el **Core Domain** del sistema siguiendo DDD.

Será responsable de:

## Agent Orchestration

- Coordinator Agent
- Qualification Agent
- Recommendation Agent
- Calendar Agent
- CRM Agent
- Follow-up Agent

---

## Lead Qualification

Captura estructurada de información:

- Location
- Budget
- Mortgage
- Timeline
- Agent Preference
- Property Type
- Amenities
- Bedrooms
- Bathrooms
- Parking
- Pets
- Remote Work
- Move-in Date

---

## Recommendation Engine

Combinará:

- Base transaccional (Supabase PostgreSQL)
- Búsqueda vectorial (pgvector)
- RAG
- Reglas de negocio
- Ranking híbrido

para recomendar el Top 3 de propiedades con argumentos personalizados.

---

## RAG

Consulta de conocimiento no estructurado:

- Descripciones
- Amenities
- Vecindarios
- Escuelas
- Financiamiento
- FAQs
- Documentación
- Información comercial

---

## CRM Orchestration

Sincronización automática con:

- wacrm
- Estados del Lead
- Actividades
- Notas
- Pipeline

---

## Appointment Scheduling

Integración con Google Calendar para:

- disponibilidad
- reserva
- reprogramación
- cancelación

---

## Workflow Engine

Automatización de:

- Follow-ups
- Recordatorios
- Escalaciones
- SLA
- Hand-off

---

## Analytics

- Conversión
- Funnel
- KPIs
- Scoring
- Evaluación de modelos

---

# Integración entre Chatwoot y FastAPI

Toda la comunicación se realizará mediante interfaces públicas.

## Entrada

```
WhatsApp

Instagram

↓

Chatwoot

↓

Webhook

↓

FastAPI
```

---

## Salida

```
FastAPI

↓

Chatwoot REST API

↓

Cliente
```

---

## Human Handoff

```
FastAPI

↓

Conversation Assignment

↓

Chatwoot

↓

Agente Humano
```

---

# ¿Por qué no modificar Chatwoot?

Modificar el backend Rails implicaría mantener un fork permanente del proyecto.

Consecuencias:

- conflictos en cada actualización
- mayor costo de mantenimiento
- dificultad para adoptar nuevas versiones
- mayor riesgo operativo

En cambio, consumir únicamente:

- REST API
- Webhooks
- API Tokens

permite actualizar Chatwoot sin afectar el Core Agentic.

---

# Justificación Técnica para FastAPI

FastAPI se adopta como backend del dominio porque el ecosistema de IA moderno está centrado en Python.

Ventajas:

- Compatibilidad nativa con LangGraph, Google ADK, CrewAI, Haystack, LlamaIndex, DSPy y SDKs de OpenAI/Anthropic.
- Excelente rendimiento para cargas I/O intensivas (LLMs, Supabase, Google Calendar, Meta APIs).
- Programación asíncrona mediante ASGI.
- Integración natural con bibliotecas de Machine Learning.
- Mayor facilidad para implementar RAG, Recommendation Engines y Agentic Workflows.
- Plataforma preparada para MCP (Model Context Protocol) y futuras arquitecturas A2A (Agent-to-Agent).

---

# Arquitectura Lógica

```
                 WhatsApp Business
                        │
                 Instagram (Meta)
                        │
                        ▼
               +----------------------+
               |      Chatwoot        |
               | Communication Layer  |
               +----------------------+
                        │
             REST API / Webhooks
                        │
                        ▼
             +------------------------+
             |    FastAPI AI Core     |
             |  Modular Monolith DDD  |
             +------------------------+
                        │
        ┌───────────────┼────────────────┐
        ▼               ▼                ▼
 Recommendation      RAG Engine      Workflow
        │               │                │
        ▼               ▼                ▼
    Supabase        OpenAI        Google Calendar
                        │
                        ▼
                     wacrm CRM
```

---

# Beneficios de esta Decisión Arquitectónica

- Separación clara entre comunicación y dominio de negocio.
- Evolución independiente de Chatwoot y del motor Agentic.
- Actualizaciones de Chatwoot sin forks ni conflictos.
- Aprovechamiento completo del ecosistema Python para IA.
- Modularidad alineada con DDD y Clean Architecture.
- Preparación para extraer módulos a microservicios en el futuro sin rediseñar el dominio.
- Menor deuda técnica y mayor mantenibilidad a largo plazo.

---

# Decisión Final

**Chatwoot será tratado como un sistema externo (Upstream System / Communication Platform), mientras que FastAPI constituirá el Core Domain del producto.** Toda la lógica de negocio, inteligencia artificial, orquestación de agentes, RAG, Recommendation Engine y automatización residirá exclusivamente en FastAPI, comunicándose con Chatwoot mediante Webhooks y APIs públicas, preservando una arquitectura desacoplada, escalable y alineada con los principios de DDD, DDIA y Attribute-Driven Design.


---

# Neighborhood Intelligence Agent

## Purpose

Enhance property recommendations with external contextual intelligence obtained through Google Maps APIs and/or MCP-compatible tools.

The objective is not only to recommend the most suitable property, but also to generate personalized persuasive arguments based on the buyer's lifestyle and preferences.

---

## Responsibilities

- Discover nearby Places of Interest (POIs).
- Retrieve ratings, popularity and opening hours.
- Estimate travel times.
- Calculate walking and driving distances.
- Rank nearby amenities according to buyer preferences.
- Generate contextual selling arguments.
- Feed additional context into the Recommendation Engine.

---

## Data Sources

### Google Maps Platform

- Places API
- Nearby Search
- Place Details
- Directions API
- Distance Matrix API
- Geocoding API

or

### MCP Tools

Any MCP-compatible provider exposing geographic search capabilities.

Examples:

- Google Maps MCP
- OpenStreetMap MCP
- Foursquare MCP
- Custom GIS MCP Server

---

## Buyer Preference Matching

During qualification, the AI captures lifestyle preferences in addition to transactional requirements.

Examples:

### Family

- schools
- parks
- pediatric clinics
- playgrounds

### Young Professional

- coworking spaces
- metro stations
- gyms
- cafés
- nightlife

### Investor

- commercial centers
- business districts
- future developments
- public transportation

### Retired Buyer

- hospitals
- pharmacies
- supermarkets
- green areas

### Pet Owner

- dog parks
- veterinary clinics
- pet stores

---

## Recommendation Pipeline

```
Lead Qualification

↓

Buyer Preferences

↓

Property Search

↓

Top Candidate Properties

↓

Neighborhood Intelligence Agent

↓

Google Maps / MCP Tools

↓

Nearby Places Ranking

↓

LLM Reasoning

↓

Recommendation Engine

↓

Personalized Persuasive Narrative

↓

Top 3 Recommended Properties
```

---

## Example Prompt Context

Property

- Miraflores
- 3 bedrooms
- USD 240,000

Buyer

- Family with two children
- Works remotely
- Wants walkability
- Budget USD 250k

Neighborhood Intelligence

- 3 highly rated schools within 800m
- 2 parks within 5-minute walk
- Fiber internet available
- Supermarket 300m
- Metro station 700m
- Children's hospital 6 minutes away

LLM Output

"This property is particularly suitable for your family because your children would have access to three highly rated schools within walking distance, two nearby parks for outdoor activities, and essential services such as supermarkets and healthcare facilities. Since you work remotely, the neighborhood also offers reliable fiber connectivity and several coworking spaces within a short drive."

---

# Recommendation Engine 2.0

The Recommendation Engine combines multiple ranking strategies:

- Structured filtering (budget, location, bedrooms, bathrooms)
- Vector similarity search (pgvector + RAG)
- Business rules
- Buyer preference matching
- Neighborhood Intelligence
- LLM reasoning
- Persuasive explanation generation

Ranking Score

```
Overall Score =

0.30 Semantic Similarity
+ 0.20 Budget Match
+ 0.15 Location Match
+ 0.10 Amenities Match
+ 0.10 Timeline Match
+ 0.10 Neighborhood Intelligence Score
+ 0.05 Agent Business Rules
```

---

# Future Evolution

Neighborhood Intelligence can evolve into an independent bounded context exposing reusable services:

- Lifestyle Score
- Walkability Score
- School Quality Score
- Safety Score
- Commute Score
- Investment Potential Score
- Future Urban Development Score
- Environmental Quality Score

These scores can be reused by Recommendation, CRM, Marketing Automation, Lead Scoring and future AI agents without coupling them to Google Maps APIs.