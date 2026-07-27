# Enriquecimiento US-214

> Output del skill `enrich-us` (invocado manualmente para US-214). Documentado en `openspec/changes/`
> siguiendo el mismo precedente que `openspec/specs/lead-qualification/us-202-205-enrichment.md`.

Fuente original: `Documents/Oficial/HU_Calificacion_Recomendacion.md` — US-214 [NUEVA].
Codigo auditado: `app/modules/lead_qualification/application/lead_scoring.py`,
`app/modules/lead_qualification/domain/models.py` (`BuyerProfile`, `PROFILE_DIMENSIONS`),
`app/modules/lead_qualification/infrastructure/{repository,db_models}.py`,
`alembic/versions/0019_outbox_retry_backoff.py` (head revision al momento de este cambio).

Busqueda de `OwnershipPolicyEngine` en el codigo: no existe (solo `ownership_policy.py` bajo
`conversation_ownership`, un motor distinto -- de asignacion de conversacion humano/bot, no de
scoring). El ticket lo menciona como consumidor futuro; este cambio se acota a **producir** el
score/readiness (no fabricar un consumidor inexistente).

---

## Original

> #### US-214 [NUEVA] -- LeadReadinessService: score continuo + urgencia + readiness financiera
>
> Como AI Agent quiero un score continuo ponderado (intencion, presupuesto, zona, horizonte, forma de
> pago, decisor) ademas de la clasificacion Hot/Warm/Cold binaria por objeciones, y una readiness
> financiera en 3 estados (READY/PRE-READY/DISCOVERY), para alimentar tanto el disparo temprano de
> recomendacion como el Ownership Policy Engine.
>
> ```gherkin
> Feature: Readiness continua del lead
> Scenario: Perfil parcial pero con senales fuertes de urgencia
>   Given BuyerProfile con financing_type, timeline y locations capturados (no todas las 7 dimensiones)
>   When LeadReadinessService.evaluate se ejecuta
>   Then retorna un score continuo ponderado (no solo Hot/Warm/Cold)
>   And clasifica financing_readiness en READY, PRE-READY o DISCOVERY
>   And el resultado alimenta tanto al Coordinator (trigger de recomendacion temprana, US-215) como al
>   OwnershipPolicyEngine
> ```
>
> **Alineacion**: (a) Transversal a Discovery/Recommendation. (b) Capa agentic: no existe -- extiende
> (no reemplaza) `LeadScoringService`
> (`app/modules/lead_qualification/application/lead_scoring.py`, umbrales
> `_HOT_THRESHOLD`/`_WARM_THRESHOLD` ya existentes) -- mismo servicio, nueva dimension de salida.
> (c) Extiende `buyer_profiles` o `leads` con columna(s) para financing_readiness y el score continuo
> (migracion nueva). (d) `LeadScoringService.record_objection` hoy solo baja de un score inicial de
> 100 por objeciones (`100 - 15*tipos - 5*total`); no incorpora presupuesto/zona/horizonte/decisor
> como senales positivas.

## Enhanced

**Funcionalidad completa**

`LeadReadinessService.evaluate(profile: BuyerProfile) -> LeadReadinessResult` computa, de forma
determinista (sin LLM), dos salidas independientes de `LeadScoringService`'s Hot/Warm/Cold:

1. Un **score continuo ponderado 0-100** (`readiness_score`), sumando puntos por cada una de las
   seis senales nombradas en el ticket, mapeadas 1:1 a campos ya existentes de `BuyerProfile`:
   - intencion -> `property_type`
   - presupuesto -> `budget`
   - zona -> `locations`
   - horizonte -> `timeline` (ponderado por urgencia: `immediate` pesa mas que `exploring`)
   - forma de pago -> `financing_type` (ponderado por certeza de pago: `cash`/`mortgage_approved`
     pesan mas que `evaluating`)
   - decisor -> `decision_maker_mode`
2. Una clasificacion de **`financing_readiness`** en 3 estados (`READY`/`PRE_READY`/`DISCOVERY`),
   determinista, basada en que combinacion de `financing_type`/`timeline`/`locations` esta capturada
   (ver design.md Decision 2 para la regla exacta).

El servicio es **aditivo**: no modifica `LeadScoringService.compute_lead_score`/`classify`, ni
`Lead.lead_score`/`lead_classification`, ni el flujo de objeciones (US-209). Es una nueva dimension de
salida, persistida en columnas nuevas.

**Campos a actualizar**

- `buyer_profiles.readiness_score` (`Float`, nullable) -- score continuo 0-100.
- `buyer_profiles.financing_readiness` (`String(16)`, nullable) -- `ready`/`pre_ready`/`discovery`.
- Elegido `buyer_profiles` (no `leads`) porque el score deriva 100% de campos de `BuyerProfile`, no de
  campos de `Lead` (que son el espejo de wacrm, CON-2) -- mismo precedente que `ai_profile`
  (US-211, columna derivada en `buyer_profiles`, no en `leads`).

**Endpoints / puntos de entrada**

Sin endpoint HTTP nuevo en este alcance -- mismo gap documentado en US-202-205: no hay una via
conversacional real que invoque el Qualification Flow todavia end-to-end con recomendacion temprana
(US-215, fuera de este alcance). `LeadReadinessService.evaluate` queda disponible como servicio de
aplicacion para ser invocado por el futuro Coordinator turn (US-215) y por cualquier tarea batch/API
de soporte que se agregue despues.

**Archivos/modulos a modificar**

- `app/modules/lead_qualification/domain/models.py` -- nuevo enum `FinancingReadiness` (junto a
  `LeadClassification`).
- `app/modules/lead_qualification/application/lead_readiness.py` -- **nuevo**, `LeadReadinessService`,
  `compute_readiness_score`, `classify_financing_readiness`, `LeadReadinessResult`.
- `app/modules/lead_qualification/infrastructure/db_models.py` -- dos columnas nuevas en
  `BuyerProfileORM`.
- `app/modules/lead_qualification/infrastructure/repository.py` -- `BuyerProfileRepository.set_readiness`
  (mismo patron que `set_ai_profile`: escritor unico y aislado, no parte de `save()`).
- `alembic/versions/0020_lead_readiness_score.py` -- **nueva migracion**.
- `tests/test_lead_readiness_service.py` -- **nuevo**.

**Definicion de Hecho**

- [ ] `compute_readiness_score` cubre: perfil vacio (0.0), perfil parcial con senales de urgencia
      (el escenario Gherkin del ticket), perfil completo (100.0 cuando todas las senales estan en su
      tier maximo).
- [ ] `classify_financing_readiness` cubre los 3 estados con al menos un caso cada uno.
- [ ] `LeadScoringService` y sus tests (`tests/test_lead_objections.py`) permanecen sin cambios de
      comportamiento (verificado corriendo la suite completa).
- [ ] Persistencia verificada: `evaluate()` escribe `readiness_score`/`financing_readiness` en la fila
      `buyer_profiles` correspondiente al `lead_id`, sin tocar ningun otro campo.
- [ ] Migracion aplica y revierte limpiamente (`upgrade`/`downgrade`).

**Documentacion y tests**

- `tests/test_lead_readiness_service.py`: formula de score por combinacion de senales, los 3 estados
  de `financing_readiness`, persistencia (fila existente y fila inexistente -- comportamiento
  `set_ai_profile`-like de "no crea fila nueva").
- Este `enriched-ticket.md` + `design.md` documentan la formula/pesos elegidos (no hay ADR previo que
  cubra scoring continuo).

**No funcionales**

- Determinismo: sin llamada a LLM, mismo criterio que `compute_lead_score`/`classify` -- reproducible
  y auditable.
- Multi-tenant: `evaluate()` opera sobre un `BuyerProfile` ya resuelto por el caller (que ya valido
  `organization_id`), no repite el check -- igual precedente que `set_ai_profile`.
- Rendimiento: computo en memoria O(1), sin queries adicionales mas alla de la escritura final.
- Extensibilidad: pesos/umbrales como constantes de modulo (mismo estilo que
  `_PENALTY_PER_DISTINCT_TYPE`/`_HOT_THRESHOLD` en `lead_scoring.py`), faciles de tunear sin tocar la
  logica.
