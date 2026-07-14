# Enriquecimiento US-202, US-203, US-204, US-205

> Output del skill `enrich-us` (invocado como `/enrich-us 202, 203, 204, 205`). Documentado aquí por
> pedido explícito del usuario: "los outputs de la skill deben quedar documentadas en openspec/specs".

Fuente original: `Documents/Oficial/HU_Calificacion_Recomendacion.md` (líneas 78-160).
Código auditado: `app/modules/lead_qualification/domain/models.py`,
`app/modules/lead_qualification/application/profile_capture.py`,
`app/modules/lead_qualification/infrastructure/{repository,db_models}.py`,
`Documents/Oficial/Agentic_System.md` (Qualification Flow, patrón #1 Prompt Chaining).

Hallazgo transversal a las 4 HUs: el dominio (`BuyerProfile.apply`) y el servicio de aplicación
(`BuyerProfileCaptureService.update_profile`) están completos y testeados, pero **no existe ningún
punto de entrada que invoque `update_profile` desde la conversación real** — no hay API router bajo
`app/modules/lead_qualification/api/`, ni un "Qualification Flow" LLM que extraiga la dimensión del
mensaje del lead y arme el `ProfilePatch`. Por eso las 4 HUs están "Parcial": la mitad determinista
(persistencia + gate) existe; la mitad agentic (extracción NLU + orquestación conversacional) es un
gap compartido, no específico de cada dimensión.

---

## US-202 — Capturar dimensión de presupuesto del perfil

### Original

> Como AI Agent quiero registrar el rango de presupuesto que declara el lead para poder evaluarlo en el
> Completeness Gate.
>
> ```gherkin
> Feature: Captura de presupuesto
> Scenario: Lead declara presupuesto
>   Given Conversation State = Discovery
>   When el lead envía un rango o monto de presupuesto
>   Then BuyerProfile.budget se actualiza con un MoneyRange
>   And "budget" aparece en captured_dimensions()
> ```
>
> **Alineación**
> - (a) Estado FSM: Discovery (QUALIFICATION) — no transiciona por sí sola.
> - (b) Capa agentic: Qualification Flow (prompt chaining) — diseño en Agentic_System.md, sin
>   implementación LLM aún; la extracción hoy la hace `BuyerProfileCaptureService.update_profile`.
> - (c) Tablas: `buyer_profiles`, `leads`.
> - (d) Implementado hoy: `BuyerProfile.apply(patch)` en `lead_qualification/domain`.

### Enhanced

**Funcionalidad completa**

Cuando el lead está en `ConversationState.QUALIFICATION` y su mensaje contiene una expresión de
presupuesto (monto único, rango, o aproximado con moneda opcional), el sub-prompt "budget" del
Qualification Flow debe:

1. Extraer `minimum`/`maximum` en la moneda declarada (o la moneda por defecto de la organización si
   no se especifica) y construir un `ProfilePatch(budget=MoneyRange(minimum, maximum))`.
2. Invocar `BuyerProfileCaptureService.update_profile(lead_id, patch)` dentro de la misma transacción
   que persiste el turno de conversación.
3. Manejar `ProfileValidationError` (monto <= 0, o `minimum > maximum`) devolviendo al lead una
   reformulación conversacional del rango, sin persistir el patch inválido.
4. Si `update_profile` retorna completeness >= threshold y antes no lo estaba, el `ProfileCompleted`
   ya emitido por el servicio dispara el sync a wacrm (US-206/US-207) — no hay trabajo adicional acá.

**Campos a actualizar**

- `BuyerProfile.budget: MoneyRange(minimum: float, maximum: float)`.
- Persistido en `buyer_profiles.budget_min`, `buyer_profiles.budget_max` (`BuyerProfileORM`).
- `buyer_profiles.updated_at` se actualiza automáticamente vía `BuyerProfile.apply`.

**Endpoints / puntos de entrada**

Gap explícito: no existe un endpoint HTTP para esta captura porque el flujo real es
conversación → Qualification Flow (LLM) → `update_profile` en proceso, no una llamada REST externa.
Si se requiere un endpoint de soporte/QA para pruebas manuales o replays, exponer:

- `POST /api/v1/leads/{lead_id}/profile/budget`
  - Body: `{"minimum": number, "maximum": number, "currency"?: string}`
  - 200: `{"completeness": number, "captured_dimensions": string[]}`
  - 404: lead no encontrado (`LeadNotFoundError`)
  - 422: `ProfileValidationError` (monto inválido)
  - Requiere `organization_id` en contexto (multi-tenant, ver `app/core/organization_context.py`).

**Archivos/módulos a modificar**

- `app/modules/lead_qualification/api/router.py` — **nuevo**, expone el endpoint anterior (o el
  Qualification Flow interno si se prioriza la vía LLM sobre la REST).
- `app/modules/lead_qualification/application/qualification_flow.py` — **nuevo**, sub-prompt de
  extracción de `budget` (patrón Prompt Chaining, Agentic_System.md #1); construye el `ProfilePatch`
  y llama a `BuyerProfileCaptureService.update_profile`.
- `app/modules/lead_qualification/application/profile_capture.py` — sin cambios funcionales; verificar
  que `update_profile` siga siendo el único punto de escritura.
- `app/main.py` — registrar el nuevo router si se opta por el endpoint HTTP.

**Definición de Hecho**

- [ ] Extracción de presupuesto integrada al Qualification Flow (o endpoint de soporte si se decide
      diferir el LLM).
- [ ] Casos cubiertos: monto único ("tengo 200 mil"), rango explícito ("entre 150k y 200k"),
      presupuesto con moneda distinta a la default de la organización, mensaje ambiguo sin monto
      (no debe generar `ProfilePatch`, debe re-preguntar).
- [ ] `ProfileValidationError` se traduce a mensaje conversacional, no a error 500 ni excepción sin
      capturar.
- [ ] `ProfileCompleted` se verifica end-to-end cuando budget es la última dimensión faltante.
- [ ] Code review + security review (multi-tenant: `organization_id` del lead, no del request).

**Documentación y tests**

- Actualizar `Documents/Oficial/HU_Calificacion_Recomendacion.md` línea 537: `Parcial` → `Implementado`
  solo cuando el punto de entrada conversacional exista (no basta con el endpoint de soporte).
- Tests unitarios: extracción de rangos/montos con distintos formatos (ya cubierto en parte por
  `tests/test_buyer_profile.py`; agregar casos de moneda y ambigüedad al nuevo Qualification Flow).
- Test de integración: turno de conversación completo → `buyer_profiles.budget_min/max` persistido.

**No funcionales**

- Seguridad: validar que el `lead_id` pertenece a la `organization_id` de la sesión autenticada antes
  de aplicar el patch (evitar cross-tenant write).
- Observabilidad: loggear (sin PII de más) cuándo una extracción de presupuesto fue rechazada por
  `ProfileValidationError`, para tunear el prompt.
- Performance: el sub-prompt de extracción debe correr dentro del presupuesto de latencia del turno
  conversacional (Agentic_System.md fija contexto 5/5 solo mensajes iniciales — no aplica retrieval
  pesado acá).

---

## US-203 — Capturar dimensión de ubicación

### Original

> Como AI Agent quiero registrar la(s) zona(s) de interés del lead para acotar el inventario relevante.
>
> ```gherkin
> Feature: Captura de ubicación
> Scenario: Lead menciona distrito o zona
>   Given Conversation State = Discovery
>   When el lead provee uno o más distritos/zonas
>   Then BuyerProfile.locations se actualiza con la tupla de zonas
>   And "locations" aparece en captured_dimensions()
> ```
>
> **Alineación**
> - (a) Discovery (QUALIFICATION).
> - (b) Qualification Flow (diseño, no implementado como LLM); ejecución actual vía `update_profile`.
> - (c) `buyer_profiles`.
> - (d) Implementado: `BuyerProfile.locations: tuple[str]`.

### Enhanced

**Funcionalidad completa**

El sub-prompt "locations" del Qualification Flow extrae uno o más distritos/zonas del mensaje del
lead (soporta multi-zona: "Miraflores o San Isidro"), normaliza contra el catálogo de zonas conocido
por la organización (si existe) y construye `ProfilePatch(locations=(...))`. Igual que US-202, viaja
por `BuyerProfileCaptureService.update_profile`.

**Campos a actualizar**

- `BuyerProfile.locations: tuple[str, ...]` — no vacío por contrato (`ProfilePatch.__post_init__`
  rechaza tupla vacía).
- Persistido en `buyer_profiles.locations` (columna `JSON`, `BuyerProfileORM`).

**Endpoints / puntos de entrada**

Mismo gap que US-202. Endpoint de soporte simétrico:

- `POST /api/v1/leads/{lead_id}/profile/locations`
  - Body: `{"locations": string[]}`
  - 200/404/422 igual que US-202.

**Archivos/módulos a modificar**

- Mismo `qualification_flow.py` (US-202) — agrega el sub-prompt "locations" al mismo módulo de
  Prompt Chaining en vez de duplicar infraestructura por dimensión.
- `app/modules/lead_qualification/api/router.py` si se expone el endpoint de soporte.
- Si existe (o se crea) un catálogo de zonas por organización, definir dónde vive la normalización —
  hoy no hay tabla de referencia; documentar como decisión abierta si el scope lo requiere.

**Definición de Hecho**

- [ ] Extracción soporta 1 y N zonas en un mismo mensaje.
- [ ] Normalización de nombres (mayúsculas/tildes/alias comunes) antes de persistir, o decisión
      explícita de NO normalizar en este sprint (documentarlo).
- [ ] Mensaje sin zona reconocible no genera patch vacío (ya garantizado por
      `ProfilePatch.__post_init__`, pero el Qualification Flow debe re-preguntar en vez de fallar).
- [ ] Code review + security review.

**Documentación y tests**

- Igual patrón que US-202: actualizar tabla resumen en `HU_Calificacion_Recomendacion.md` solo cuando
  el flujo conversacional real exista.
- Tests: multi-zona, zona con error tipográfico, zona fuera de cobertura de la organización (definir
  comportamiento: ¿se acepta igual o se marca para revisión humana?).

**No funcionales**

- Mismo tenant-isolation, logging y latencia que US-202.
- Si se normaliza contra catálogo, cachear el catálogo por organización para no pagar una query extra
  por turno.

---

## US-204 — Capturar dimensión de tipo de propiedad

### Original

> Como AI Agent quiero registrar el tipo de propiedad buscado para filtrar el inventario correctamente.
>
> ```gherkin
> Feature: Captura de tipo de propiedad
> Scenario: Lead indica tipo de propiedad
>   Given Conversation State = Discovery
>   When el lead menciona casa, departamento u otro PropertyType
>   Then BuyerProfile.property_type se actualiza
>   And "property_type" aparece en captured_dimensions()
> ```
>
> **Alineación**
> - (a) Discovery (QUALIFICATION).
> - (b) Qualification Flow (diseño); ejecución vía `update_profile`.
> - (c) `buyer_profiles`.
> - (d) Implementado: `PropertyType` enum + `BuyerProfile.property_type`.

### Enhanced

**Funcionalidad completa**

El sub-prompt "property_type" clasifica el mensaje del lead contra el enum cerrado
`PropertyType` (`apartment | house | land | commercial | other`) y arma
`ProfilePatch(property_type=...)`. A diferencia de budget/locations, esta dimensión es de clasificación
categórica simple (una sola llamada, sin parsing numérico), por lo que puede resolverse con un prompt
más corto o incluso una heurística de keywords + fallback LLM para el caso "other"/ambiguo.

**Campos a actualizar**

- `BuyerProfile.property_type: PropertyType | None`.
- Persistido en `buyer_profiles.property_type` (`String(32)`, `BuyerProfileORM`).

**Endpoints / puntos de entrada**

- `POST /api/v1/leads/{lead_id}/profile/property-type`
  - Body: `{"property_type": "apartment"|"house"|"land"|"commercial"|"other"}`
  - 422 si el valor no matchea el enum (validación Pydantic, no llega a `ProfileValidationError` porque
    el dominio no valida el enum — lo valida el tipo mismo).

**Archivos/módulos a modificar**

- Mismo `qualification_flow.py` — sub-prompt "property_type".
- `app/modules/lead_qualification/api/router.py` (si aplica endpoint de soporte).
- Revisar si el enum `PropertyType` necesita ampliarse (ej. "oficina", "terreno agrícola") según el
  inventario real de `app/modules/recommendation` — hoy no hay evidencia de mismatch, pero es un riesgo
  a validar contra `properties` (Supabase) antes de cerrar el sub-prompt.

**Definición de Hecho**

- [ ] Cobertura de sinónimos comunes en español (depa/departamento, casa/vivienda, terreno/lote).
- [ ] Caso "menciona dos tipos" (ej. "casa o departamento, lo que salga primero") — definir si se
      captura el primero, se pide desambiguar, o se deja `property_type=None` hasta que el lead decida.
- [ ] Mapeo verificado 1:1 contra los valores de tipo de propiedad usados en `StructuredFilterService`
      (Recommendation) para evitar que un `property_type` capturado nunca matchee inventario.

**Documentación y tests**

- Tests de clasificación con sinónimos y con mensajes ambiguos.
- Test de integración cross-módulo (opcional, si hay tiempo): un `property_type` capturado en
  Qualification debe ser un valor válido de filtro en Recommendation.

**No funcionales**

- Mismo tenant-isolation y logging que US-202/203.
- Esta dimensión es la más barata de las 4 en tokens/latencia — candidata a resolverse sin LLM
  (regex/keyword matching) si el presupuesto de latencia del Coordinator Agent es ajustado.

---

## US-205 — Capturar horizonte de decisión y must-haves

### Original

> Como AI Agent quiero registrar el timeline de compra y los atributos indispensables para priorizar
> recomendaciones y detectar urgencia comercial.
>
> ```gherkin
> Feature: Captura de timeline y must-haves
> Scenario: Lead indica urgencia y requisitos indispensables
>   Given Conversation State = Discovery
>   When el lead expresa un horizonte temporal o un requisito no negociable
>   Then BuyerProfile.timeline y/o must_haves se actualizan
>   And las dimensiones correspondientes aparecen en captured_dimensions()
> ```
>
> **Alineación**
> - (a) Discovery (QUALIFICATION).
> - (b) Qualification Flow (diseño); ejecución vía `update_profile`.
> - (c) `buyer_profiles`.
> - (d) Implementado: `Timeline` enum, `must_haves: tuple[str]`.

### Enhanced

**Funcionalidad completa**

Esta HU cubre **dos dimensiones independientes** en un mismo turno posible (`timeline` y
`must_haves`), lo que la distingue de US-202/203/204 (una dimensión cada una). El Qualification Flow
debe poder:

1. Extraer `timeline` como uno de los 5 valores del enum (`immediate | 3_months | 6_months |
   over_6_months | exploring`) cuando el lead expresa urgencia ("quiero mudarme ya", "estoy solo
   viendo opciones").
2. Extraer `must_haves` como lista de strings libres (requisitos no negociables: "3 dormitorios",
   "cochera", "cerca al colegio X") cuando el lead los menciona.
3. Ambas pueden llegar en el mismo `ProfilePatch` si el mensaje trae las dos señales, o cada una por
   separado en turnos distintos — `ProfilePatch` ya soporta esto (`timeline`/`must_haves` son campos
   independientes con `None` = "no tocar").
4. `must_haves` es texto libre, no un enum cerrado: el sub-prompt debe normalizar mínimamente (evitar
   duplicados textuales, capitalización consistente) pero no rechazar valores no catalogados —
   a diferencia de `property_type`, no hay lista cerrada que validar.

**Campos a actualizar**

- `BuyerProfile.timeline: Timeline | None`.
- `BuyerProfile.must_haves: tuple[str, ...]`.
- Persistidos en `buyer_profiles.timeline` (`String(32)`) y `buyer_profiles.must_haves` (`JSON`).

**Endpoints / puntos de entrada**

- `POST /api/v1/leads/{lead_id}/profile/timeline`
  - Body: `{"timeline": "immediate"|"3_months"|"6_months"|"over_6_months"|"exploring"}`
- `POST /api/v1/leads/{lead_id}/profile/must-haves`
  - Body: `{"must_haves": string[]}` (422 si viene vacío, por `ProfilePatch.__post_init__`).
- Considerar si conviene un único endpoint combinado (`PATCH /profile`) para el caso de un mensaje que
  trae ambas señales a la vez, evitando dos escrituras separadas a `buyer_profiles` en el mismo turno.

**Archivos/módulos a modificar**

- Mismo `qualification_flow.py` — dos sub-prompts ("timeline", "must_haves") o uno combinado si se
  decide resolver ambas señales con una sola llamada LLM por turno (más barato, pero mezcla
  responsabilidades del prompt).
- `app/modules/lead_qualification/api/router.py` si se exponen los endpoints de soporte.
- `app/modules/lead_qualification/domain/models.py` — sin cambios si el scope se mantiene en los 5
  valores actuales de `Timeline`; evaluar si "exploring" cubre bien el caso "sin apuro" del Customer
  Journey (`Customer_Journey_Residencial_WhatsApp_Detallado.md`) antes de dar la HU por cerrada.

**Definición de Hecho**

- [ ] `timeline` y `must_haves` pueden capturarse en el mismo turno o en turnos separados sin pisarse
      entre sí (`ProfilePatch` con un campo `None` no debe borrar el valor ya guardado — comportamiento
      ya garantizado por `BuyerProfile.apply`, verificar con test explícito).
- [ ] `must_haves` deduplica entradas semánticamente iguales expresadas distinto (ej. "cochera" vs
      "estacionamiento") — definir si esto es responsabilidad del prompt o si se acepta duplicado
      textual en este sprint (documentar la decisión).
- [ ] Mensaje sin señal de urgencia ni requisitos no genera patch vacío (ya bloqueado por
      `ProfilePatch.is_empty()` en `update_profile`, que lanza `ProfileValidationError` — verificar que
      el Qualification Flow simplemente no llame a `update_profile` en ese caso, en vez de dejar que la
      excepción llegue al usuario).

**Documentación y tests**

- Tests: timeline solo, must_haves solo, ambos en un turno, must_haves con duplicados, timeline con
  expresión ambigua ("tal vez el próximo año" → ¿`over_6_months` o `exploring`? definir regla).
- Actualizar `HU_Calificacion_Recomendacion.md` fila US-205 solo cuando el flujo conversacional (no el
  endpoint de soporte) esté integrado.

**No funcionales**

- Mismo tenant-isolation, logging, latencia que las HUs anteriores.
- `must_haves` es texto libre generado por LLM a partir de input de usuario: sanitizar antes de
  persistir (longitud máxima por item, sin HTML/markup) para evitar que un must-have gigante o con
  contenido inesperado llegue a `buyer_profiles.must_haves` sin control.

---

## Nota de scope compartida

Las 4 HUs deberían resolverse con **un único módulo** `qualification_flow.py` (varios sub-prompts,
patrón Prompt Chaining ya documentado en `Agentic_System.md`), no cuatro implementaciones aisladas —
evita duplicar el manejo de `ProfileValidationError`, el wiring a `update_profile` y el tenant-isolation
check.
