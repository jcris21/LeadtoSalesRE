## Why

US-215 (adaptada de US-206) pide bajar `profile_completeness_threshold` (hoy 90%,
`app/core/config.py:42`) para que el `CompletenessGate` permita avanzar a
Recomendación/Matching con las 4 dimensiones principales del `BuyerProfile`
capturadas (`budget`, `locations`, `property_type`, `timeline`), dejando
`must_haves` como refinamiento posterior (Nivel 2, ver US-217), en vez de exigir
el perfil casi completo (90%). Esto habilita un flujo "recomendación-first":
el lead recibe matches útiles antes, sin esperar el quinto dato.

## What Changes

- Recalibrar el default de `profile_completeness_threshold` de `90.0` a
  `80.0` en `app/core/config.py` (justificado: `BuyerProfile` tiene 5
  dimensiones, `completeness()` = `100 * captured/5`, así que 4/5 = 80.0% es
  el único valor discreto que corresponde exactamente a "4 dimensiones
  principales capturadas").
- Actualizar `tests/test_buyer_profile.py::test_profile_completed_fires_exactly_on_crossing_threshold`,
  que usa el default de config vía `BuyerProfileCaptureService` sin threshold
  explícito, para reflejar que `ProfileCompleted` ahora se dispara al cruzar
  80% (tras `budget` + `locations` + `property_type` + `timeline`) y que la
  captura posterior de `must_haves` es refinamiento y NO re-dispara el evento.
- Añadir un test explícito que reproduzca el escenario Gherkin de US-215:
  perfil con las 4 dimensiones principales (sin `must_haves`) →
  `CompletenessGate.can_advance_to_recommendation` retorna `can_advance=True`.
- No se tocan `CompletenessGate(threshold=90.0)` en los tests que lo pasan
  explícito (siguen probando el comportamiento del gate con un umbral
  arbitrario, independiente del default de config).

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `lead-qualification-completeness-gate`: el umbral por defecto de
  completitud requerido para avanzar de Calificación a Recomendación baja de
  90% a 80%, y por lo tanto el punto de cruce en que `ProfileCompleted` se
  publica también baja de 100% (5/5 dimensiones) a 80% (4/5 dimensiones).

## Impact

- Código: `app/core/config.py` (1 constante + comentario).
- Tests: `tests/test_buyer_profile.py` (test existente ajustado + test nuevo).
- Downstream: cualquier consumidor de `ProfileCompleted`/Matching ahora
  recibe el evento con `must_haves` potencialmente vacío; el
  `RecommendationService` y el wiring de recomendación ya toleran perfiles
  parciales (5 dimensiones opcionales en el snapshot), así que no requieren
  cambios de código — solo verificación por test.
- Sin cambios de API pública, sin migraciones, sin nuevos endpoints.
