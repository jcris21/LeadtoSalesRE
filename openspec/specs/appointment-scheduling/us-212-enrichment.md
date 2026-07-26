# Enriquecimiento US-212

> Output del skill `enrich-us` (invocado como `/enrich-us US-212`). Documentado aquí por la misma
> convención que `openspec/specs/lead-qualification/us-202-205-enrichment.md`.

Fuente original: `Documents/Oficial/HU_Calificacion_Recomendacion.md` (fila resumen línea ~619,
sección completa línea ~644 "US-212 [NUEVA] — Conectar Availability Validator + Scheduling Service
al flujo conversacional").

Código auditado: `app/modules/conversation_ownership/application/coordinator.py`,
`app/modules/appointment/application/{scheduling_service,availability_validator}.py`,
`app/modules/appointment/domain/models.py`, `app/modules/appointment/infrastructure/repository.py`,
`app/modules/conversation_ownership/domain/models.py`, `app/modules/recommendation/infrastructure/repository.py`,
`openspec/specs/appointment-scheduling/spec.md`, `tests/test_scheduling_service.py`,
`tests/test_coordinator_qualification_turn.py`.

Hallazgo confirmado: `AvailabilityValidatorService` (US-402) y `SchedulingService.book_visit`
(US-404) están completos, testeados de forma aislada, y ya orquestan correctamente
Availability -> Calendar -> Appointment -> AppointmentBooked -> pipeline_stage sync. Ningún import
de `app.modules.appointment` existe en `coordinator.py` — confirmado por grep. `ConversationState`
ya declara la transición `RECOMMENDATION -> APPOINTMENT` en `ALLOWED_TRANSITIONS`
(`app/modules/conversation_ownership/domain/models.py:84`), sin código que la dispare.

---

## US-212 — Conectar Availability Validator + Scheduling Service al flujo conversacional

### Original

> Como sistema quiero que `CoordinatorAgent` invoque `AvailabilityValidatorService` y
> `SchedulingService.book_visit` cuando el lead acepta un horario, para que exista agendamiento real
> en producción (hoy ambos servicios están completos y testeados de forma aislada, pero ningún nodo
> del grafo ni `coordinator.py` los llama — confirmado por ausencia total de imports de `appointment`
> en `coordinator.py`).
>
> ```gherkin
> Feature: Agendamiento conectado al flujo conversacional
> Scenario: Lead acepta un horario propuesto
>   Given Conversation State = Recommendation (RECOMMENDATION) y un horario ya validado por
>         AvailabilityValidatorService
>   When el lead confirma el horario en el turno conversacional
>   Then CoordinatorAgent invoca SchedulingService.book_visit (re-valida disponibilidad internamente)
>   And se crea el evento en Google Calendar y se persiste Appointment
>   And se publica AppointmentBooked y Lead.pipeline_stage sincroniza APPOINTMENT_SET a wacrm
> ```
>
> **Alineación**
> - (a) Recommendation → Scheduling (RECOMMENDATION→SCHEDULING, transición hoy inexistente en código).
> - (b) Capa agentic: llamada directa desde `CoordinatorAgent.handle_message` (mismo patrón
>   determinista que `run_qualification_turn`), no requiere LLM adicional — solo un nuevo paso de
>   orquestación.
> - (c) Tablas ya existentes: `appointments` (US-402/404), `leads.pipeline_stage`.
> - (d) [GAP de wiring, no de servicio] `AvailabilityValidatorService` y
>   `SchedulingService.book_visit` (`app/modules/appointment/application/`) están implementados y
>   probados (`tests/test_availability_validator.py`, `tests/test_scheduling_service.py`); falta
>   exclusivamente el paso en `coordinator.py` que los invoque.

### Enhanced

**Funcionalidad completa**

Cuando `conversation.state is ConversationState.RECOMMENDATION` y el lead responde en el turno
conversacional confirmando un horario de visita, `CoordinatorAgent._conversational_turn` debe, ANTES
de invocar al `ResponderPort`:

1. Extraer un slot (`datetime`) del mensaje del lead mediante un reconocedor determinista
   (`extract_confirmed_slot`, sin LLM — mismo nivel de rigor que `extract_identity`): reconoce fecha
   explícita (`DD/MM` o `DD/MM/YYYY`) + hora (`H`, `H:MM`, `am`/`pm` opcional, o "a las Hh") y día de
   semana relativo (lunes…domingo, "mañana", "hoy") + hora. Un mensaje sin un slot reconocible
   devuelve `None` — nunca inventa una fecha.
2. Si no hay slot reconocible, el turno continúa sin cambios (fallback normal al `ResponderPort`) —
   este paso es puramente aditivo, igual que `_classify_intent`.
3. Si hay slot reconocible, resolver:
   - **Propiedad recomendada**: `RecommendationRepository.list_for_lead(lead_id)`, quedarse con el
     `generated_at` más reciente y, dentro de ese batch, `rank == 1`. Sin recomendaciones -> no se
     puede agendar; responder con un mensaje conversacional pidiendo elegir una propiedad primero
     (nunca un error 500 ni una excepción sin capturar).
   - **Broker**: `BrokerRepository.list_active_for_organization(organization_id)`, primer broker
     activo (MVP: sin lógica de asignación por especialidad todavía — ver Non-Goals). Sin brokers
     activos -> mismo tratamiento que sin recomendación: mensaje conversacional, no excepción.
   - **Attendee**: `Lead.contact_reference` (vía `LeadRepository`), como único elemento de la tupla
     `attendees` (el broker no tiene email capturado en el MVP — `Broker` no declara ese campo hoy).
4. Invocar `SchedulingService.book_visit(organization_id=..., lead_id=..., property_id=...,
   broker_id=..., slot=..., attendees=...)`. `SchedulingService` re-valida disponibilidad
   internamente (spec.md "Booking re-verifies availability internally") — el Coordinator nunca llama
   `AvailabilityValidatorService.check()` por separado ni asume que el slot ya está confirmado.
5. Resultado `booked`: transicionar `conversation.transition_to(ConversationState.APPOINTMENT,
   reason=...)` y devolver como respuesta del turno un mensaje de confirmación con
   `appointment.meet_link` — sin llamar al `ResponderPort` (short-circuit, mismo patrón que
   `ask_identity`/`qualification.reprompts`).
6. Resultado `SlotNotConfirmedError` (`status` = `pending` o `unavailable`): no se persiste nada
   (ya garantizado por `SchedulingService`); el turno cae de vuelta al flujo conversacional normal
   con una nota de grounding informando que el horario aún no está confirmado (mensaje
   determinista, no delegado al LLM, para evitar que el `ResponderPort` alucine una confirmación).
   `conversation.state` permanece en `RECOMMENDATION`.
7. Cualquier excepción no esperada (p. ej. `GoogleCalendarPort` caído, `OrganizationConfig` sin
   `google_workspace` configurado) debe capturarse y degradar a una respuesta conversacional
   ("no pude agendar en este momento, un asesor te contactará") — mismo contrato de resiliencia que
   `_identity_gate`'s manejo de fallos de wacrm. Nunca debe tumbar el turno completo.

**Resolución de credenciales de Google Calendar**

`SchedulingService` requiere un `GoogleCalendarPort`. No existe hoy ningún `wiring.py` en
`app/modules/appointment/`. Este cambio añade una función de construcción perezosa (mismo patrón que
`lead_qualification.wiring.build_wacrm_client`): lee `OrganizationConfigRepository.get(org_id)`, si
`google_workspace` es `None` o incompleto, el turno cae al camino de "no pude agendar" del punto 7
sin intentar construir el cliente (evita una excepción de credenciales ruidosa en logs para orgs que
aún no configuraron Calendar).

**Campos a actualizar**

- `appointments` (ya existe, US-404): sin cambios de esquema.
- `leads.pipeline_stage` -> `AppointmentSet` (ya lo hace `SchedulingService.book_visit` internamente
  vía `LeadSyncAdapter.push_profile_update`).
- `conversations.state` -> `Appointment` (nuevo: disparado por este cambio).

**Endpoints / puntos de entrada**

Ninguno nuevo — el punto de entrada sigue siendo `CoordinatorAgent.handle_message` (webhook ->
event bus -> coordinator), consistente con el resto del flujo conversacional. No se expone HTTP
directo para agendar (fuera de alcance de esta HU; ver Non-Goals).

**Archivos/módulos a modificar**

- `app/modules/conversation_ownership/application/scheduling_turn.py` — **nuevo**. Define
  `extract_confirmed_slot(text, *, reference_now)`, `SchedulingTurnResult` (dataclass:
  `outcome: Literal["booked", "not_confirmed", "no_property", "no_broker", "error", "no_slot"]`,
  `response: str | None`, `appointment: Appointment | None`), y `run_scheduling_turn(session, *,
  conversation, text, calendar_port_factory)` — orquesta los pasos 3-7 anteriores.
- `app/modules/conversation_ownership/application/coordinator.py` — en `_conversational_turn`,
  antes de construir `system_prompt`/llamar al `ResponderPort`: si
  `conversation.state is ConversationState.RECOMMENDATION`, invocar `run_scheduling_turn`; en
  `outcome == "booked"` hacer short-circuit de la respuesta (sin tocar `_qualification_turn` ni
  `_build_grounding_note`, que ya están gateados a `QUALIFICATION`).
- `app/modules/appointment/wiring.py` — **nuevo**, `build_calendar_client(session, organization_id)`
  siguiendo el patrón de `lead_qualification.wiring.build_wacrm_client`.

**Definición de Hecho**

- [ ] `extract_confirmed_slot` reconoce fecha explícita + hora, día de semana relativo + hora; un
      mensaje sin slot devuelve `None` sin excepción.
- [ ] Camino feliz: `RECOMMENDATION` + slot reconocido + disponibilidad `confirmed` (seed de
      `AvailabilityCheck`) -> `Appointment` persistido, `AppointmentBooked` publicado,
      `leads.pipeline_stage = AppointmentSet`, `conversation.state = Appointment`.
- [ ] Conflicto de disponibilidad (`pending`/`unavailable`) -> `SlotNotConfirmedError` capturado,
      cero persistencia, `conversation.state` permanece `RECOMMENDATION`, respuesta conversacional
      explicando que el horario aún no está confirmado.
- [ ] Sin recomendaciones / sin brokers activos / sin `google_workspace` configurado -> respuesta
      conversacional de fallback, nunca una excepción sin capturar hacia `handle_message`.
- [ ] `conversation.state is not RECOMMENDATION` -> el paso no se ejecuta (aditivo, cero impacto en
      `QUALIFICATION` u otros estados — no debe romper ningún test de `test_coordinator_qualification_turn.py`).
- [ ] Tests unitarios de `scheduling_turn.py` + tests de integración en `coordinator.py` (booking
      feliz, conflicto de disponibilidad, persistencia de `pipeline_stage`/`appointments`).

**Non-Goals (explícitos, fuera de alcance de este wiring)**

- Asignación de broker por especialidad/zona — MVP toma el primer broker activo.
- UI/flujo para que el lead *elija* un horario propuesto por el sistema (proponer slots) — esta HU
  solo cubre la confirmación de un horario que el lead ya menciona en texto libre.
- `ReminderSchedulerPort` real (US-213, depende de este cambio).
- Reordenamiento del turno de profundización pre-agenda (US-220) o invitación conversacional a
  visita vía prompt (US-221) — ambas dependen de este wiring pero no son parte de él.
