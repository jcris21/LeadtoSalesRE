Blueprint Funcional Propuesto
Epic 1 – Lead Intake

Objetivo

Recibir leads provenientes de cualquier canal digital.

User Story

US-101 – Crear Lead

Como AI Sales Agent

quiero crear automáticamente un Lead cuando llega un nuevo mensaje

para iniciar inmediatamente la conversación.

Acceptance Criteria
Feature: Lead Creation

Scenario: New WhatsApp lead
Given no Lead exists with the sender phone number
When a WhatsApp message is received
Then create a new Lead
And create a new Conversation
And assign Conversation State = New
And assign Opportunity Stage = New
And send the welcome message
Epic 2 – Conversation Qualification
US-201

Como AI Agent

quiero descubrir las necesidades del cliente

para recomendar únicamente propiedades relevantes.

Feature: Discovery

Scenario: Complete qualification
Given Conversation State = Discovery
When the lead provides
    | budget |
    | location |
    | property type |
Then Requirement Profile becomes Complete
And Conversation State changes to Recommendation
And Opportunity Stage changes to Qualified
Epic 3 – Recommendation Engine
US-301

Como comprador

quiero recibir propiedades compatibles

para evaluar opciones rápidamente.

Feature: Property Recommendation

Scenario: Match found

Given Requirement Profile is Complete

When Recommendation Engine executes

Then return at least three compatible listings

And rank them by relevance

And store Recommendation Session
Epic 4 – Appointment Scheduling
US-401

Como comprador

quiero agendar una visita

para conocer el inmueble.

Feature: Appointment

Scenario: Schedule visit

Given Property is Available

And Broker is Available

When customer accepts a proposed slot

Then create Appointment

And Appointment State = Confirmed

And send Calendar Invite

And Opportunity Stage = Visit
Epic 5 – Visit
Scenario: Visit completed

Given Appointment State = Confirmed

When broker marks visit completed

Then Appointment State = Completed

And Conversation enters Follow-up

And ask customer for feedback
Epic 6 – Offer
Scenario: Offer submitted

Given Visit has been completed

When customer submits an offer

Then create Offer

And Opportunity Stage = Negotiation
Epic 7 – Closing
Scenario: Sale completed

Given Reservation is signed

When payment is confirmed

Then Opportunity Stage = Won

And trigger Post Sale workflow
Historias Técnicas

No todo son historias funcionales.

También tendrás historias técnicas.

Ejemplo.

TS-101

Persist Conversation FSM.

Scenario

Given Conversation State changes

When transition succeeds

Then persist transition

And publish ConversationStateChanged event
TS-102

Persist Opportunity FSM.

TS-103

Persist Appointment FSM.

TS-104

Outbox Event.

TS-105

Audit Log.

Historias para IA

También separaría las historias del AI Agent.

AI-101

Intent Detection.

Given a customer message

When LLM classifies intent

Then confidence must be greater than configured threshold

Otherwise request clarification
AI-102

Requirement Extraction.

AI-103

Recommendation Ranking.

AI-104

Appointment Suggestion.

AI-105

Conversation Summary.

Organización del Backlog

En lugar de organizar el backlog por pantallas, lo organizaría por capacidades de negocio:

Epic	Capability	Bounded Context
EP-01	Lead Intake	Lead Management
EP-02	Conversation	Conversation
EP-03	Qualification	Recommendation
EP-04	Recommendation	Recommendation
EP-05	Scheduling	Appointment
EP-06	Visit	Appointment
EP-07	Negotiation	Sales
EP-08	Closing	Sales
EP-09	Follow-up	Marketing Automation
EP-10	Analytics	Reporting

## Anexo: Plan de implementación por sprints (Epic 2 y Epic 3)

Epic 2 (Qualification, US-201) y Epic 3 (Recommendation Engine, US-301) están descritas arriba como cajas
únicas en Gherkin. El catálogo completo de Historias de Usuario que las descompone — con criterio INVEST,
formato Gherkin y alineación a FSM/capa agentic/tablas Supabase — vive en
`Documents/Oficial/HU_Calificacion_Recomendacion.md` (US-202 a US-211 para Epic 2; US-302 a US-310 más
AI-104 para Epic 3; **AI-102** de esta lista de Historias para IA queda desarrollada ahí como "Extraer
señales libres de la conversación hacia `conversation_memory`").

Ese catálogo se secuencia en sub-sprints (detalle completo con Definition of Done en
`Documents/Oficial/ImplementationPlan.md`, sección "Sprint 2/3 — Fase 2"):

| Sub-sprint | HUs | Depende de |
|---|---|---|
| Sprint 2.1 (paralelizable) | US-208, US-209, AI-102 | Sprint 2 (US-202–207, ya implementado) |
| Sprint 2.2 | US-211 | Sprint 2.1 (AI-102) |
| Sprint 3.1 (paralelizable, prioridad máxima) | US-309, US-308, US-310 | Ninguna — US-309 es un bug activo de esquema |
| Sprint 3.2 | US-303, US-304 | Sprint 3.1 (US-309 y US-308 respectivamente) |
| Sprint 3.3 | AI-104 | Sprint 3.1/3.2 (no bloqueante, se secuencia al final) |

Regla de secuenciamiento: Sprint 2.1/2.2 y Sprint 3.1/3.2/3.3 no tienen dependencia dura entre sí (pueden
correr en paralelo); la única conexión cruzada es que **US-211** (Epic 2) puede alimentar como signal
opcional al Ranking Engine de Epic 3 (US-305) una vez completo — mejora, no bloqueo.