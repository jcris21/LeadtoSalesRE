Máquina de Estados (3 Tabla)

| Máquina de Estados        | Propósito                                                            | Consumidor Principal           | Granularidad | Persistencia   | Ejemplos de Estados                                                                        |
| ------------------------- | -------------------------------------------------------------------- | ------------------------------ | ------------ | -------------- | ------------------------------------------------------------------------------------------ |
| **Conversation FSM**      | Controlar el flujo de la conversación y las acciones de la IA.       | AI Sales Agent, Orchestrator   | Alta         | `Conversation` | New, Greeting, Discovery, Recommendation, Scheduling, Waiting Response, Follow-up, Handoff |
| **Opportunity FSM (CRM)** | Representar el avance comercial del lead para gestión y forecasting. | Broker, Gerente Comercial, CRM | Baja         | `Opportunity`  | New, Qualified, Visit, Negotiation, Won, Lost, Nurturing                                   |
| **Appointment FSM**       | Administrar el ciclo de vida de las visitas.                         | Broker, Calendar Service       | Media        | `Appointment`  | Requested, Pending Confirmation, Confirmed, Rescheduled, Completed, Cancelled, No Show     |



1. Conversation FSM (IA)

Pregunta que responde:

¿Qué debe hacer la IA ahora?
| Estado           | Objetivo                  | Acción principal de la IA          | Evento de salida           |
| ---------------- | ------------------------- | ---------------------------------- | -------------------------- |
| New              | Recibir el primer mensaje | Saludar e identificar el anuncio   | Contact establecido        |
| Greeting         | Generar confianza         | Presentarse y confirmar interés    | Intención detectada        |
| Discovery        | Descubrir necesidades     | Hacer preguntas de calificación    | Información suficiente     |
| Recommendation   | Recomendar propiedades    | Buscar y enviar opciones           | Solicitud de visita        |
| Scheduling       | Coordinar visita          | Proponer horarios disponibles      | Horario aceptado           |
| Waiting Response | Esperar respuesta         | Enviar recordatorios automáticos   | Respuesta recibida         |
| Follow-up        | Reactivar conversación    | Enviar contenido o nuevas opciones | Lead reactivado            |
| Handoff          | Transferir al broker      | Entregar contexto completo         | Broker acepta conversación |

2. Opportunity FSM (CRM)

Pregunta que responde:

¿Cómo avanza esta oportunidad comercial?

| Estado CRM  | Criterio de entrada                     | Objetivo Comercial    | Responsable |
| ----------- | --------------------------------------- | --------------------- | ----------- |
| New         | Lead creado                             | Primer contacto       | IA          |
| Qualified   | Lead con potencial real                 | Convertir en visita   | IA          |
| Visit       | Existe una visita propuesta o realizada | Lograr oferta         | Broker      |
| Negotiation | Hay una oferta activa                   | Cerrar la venta       | Broker      |
| Won         | Venta concretada                        | Postventa y referidos | Broker      |
| Lost        | Oportunidad descartada                  | Registrar motivo      | Broker      |
| Nurturing   | Compra no inmediata                     | Mantener relación     | IA          |


3. Appointment FSM

Pregunta que responde:

¿Cuál es el estado actual de la visita?

| Estado               | Descripción                      | Evento siguiente        |
| -------------------- | -------------------------------- | ----------------------- |
| Requested            | Cliente solicita una visita      | Pending Confirmation    |
| Pending Confirmation | Esperando validar disponibilidad | Confirmed / Cancelled   |
| Confirmed            | Visita confirmada                | Completed / Rescheduled |
| Rescheduled          | Fecha modificada                 | Confirmed               |
| Completed            | Visita realizada                 | Feedback / Offer        |
| Cancelled            | Cancelada                        | Requested               |
| No Show              | Cliente no asistió               | Reprogramar o Lost      |
