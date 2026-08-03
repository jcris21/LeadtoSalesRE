
▎ Feature: Dimensiones adicionales de calificación
 Como Product Owner quiero que BuyerProfile capture financiamiento y modo de decisión (solo/pareja/familia) para cerrar la brecha entre el Customer Journey documentado y el modelo de dominio actual.
▎
▎ Feature: Dimensiones adicionales de calificación
▎ Scenario: Lead declara forma de pago
▎   Given Conversation State = Discovery
▎   When el lead indica contado, crédito hipotecario, crédito preaprobado o "evaluando"
▎   Then BuyerProfile.financing_type se actualiza (campo nuevo)
▎   And PROFILE_DIMENSIONS se extiende a 6 elementos (o se documenta explícitamente por qué no)

Enhanced                                                                                                    
Contexto técnico verificado: PROFILE_DIMENSIONS (app/modules/lead_qualification/domain/models.py:56) hoy tiene 5 elementos: budget, locations, property_type, timeline, must_haves. BuyerProfile/ProfilePatch son inmutables (dataclass(frozen=True) para ProfilePatch,  para BuyerProfile). Extracción es
Loaded C:\Users\ASUS\.claude\rules\testing.md

US-208 Enrichment                                                                  
Original                                                                           
▎ Como Product Owner quiero que BuyerProfile capture financiamiento y modo de decis▎ cerrar la brecha entre el Customer Journe dominio actual.
▎
▎ Feature: Dimensiones adicionales de calificación                                 ▎ Scenario: Lead declara forma de pago
▎   Given Conversation State = Discovery
▎   When el lead indica contado, crédito hipotecario, crédito preaprobado o "evaluando"
▎   Then BuyerProfile.financing_type se actualiza (campo nuevo)
▎   And PROFILE_DIMENSIONS se extiende a 6 elementos (o se documenta explícitamente
Enhanced                                                                           
Contexto técnico verificado: PROFILE_DIMENSIONS (app/modules/lead_qualification/domelementos: budget, locations, property_typerProfile/ProfilePatch son inmutables(dataclass(frozen=True) para ProfilePatch, entidad mutable vía .apply() para BuyerProfile). Extracción es regex/keyword determinista en qualification_flow.py, sin LLM, siguiendo el patrón dBuyerProfileCaptureService.update_profile c00 * captured / len(PROFILE_DIMENSIONS) —extender a 6 dimensiones cambia automáticamente el umbral relativo sin tocar profile_completeness_threshold.
                                                                                   Decisión de alcance: la HU original mencion, decision_maker_mode) pero el Gherkin solocubre financiamiento. Se decide implementar ambos como incremento único de PROFILE_DIMENSIONS (queda en 7, no 6, si se cuentan las 5 actuales + 2 nuevas) — o alternativamente, documentar que solo fincompleteness y decision_maker_mode es metadRecomendación: ambos cuentan comodimensiones nuevas (PROFILE_DIMENSIONS pasa de 5 a 7), porque el Customer Journey los describe como igual de relevantes para priorización comercial y US-209 (Hot/Warm/Cold) los va a consumir. 
Funcionalidad completa
                                                                                   1. Nuevo enum FinancingType (domain/models., MORTGAGE_PREAPPROVED, EVALUATING (mapea1:1 a "contado, crédito hipotecario, crédito preaprobado, evaluando").
2. Nuevo enum DecisionMakerMode: SOLO, COUPLE, FAMILY.                             3. PROFILE_DIMENSIONS se extiende a ("budgeype", "timeline", "must_haves","financing_type", "decision_maker_mode").
4. ProfilePatch: agregar financing_type: FinancingType | None = None y decision_maker_mode: DecisionMakerMode | None = None. is_empty() ya itera sobre PROFILE_DIMENSIONS vía getattr, así que no requiere cambio si los nombres de atributo coinciden.                                                                5. BuyerProfile: agregar los dos campos al red_dimensions().
6. BuyerProfileCaptureService._snapshot(): incluir los dos campos nuevos en el dict publicado en ProfileCompleted.
                                                                                   Campos a actualizar (tabla buyer_profiles)
                                                                                   ┌─────────────────────┬────────────────────────────────────────────────────────────┐
│       Columna       │        Tipo        │ Nullable │                         Not├─────────────────────┼────────────────────────────────────────────────────────────┤
│ financing_type      │ VARCHAR            │ sí       │ valores: cash, mortgage_approved,                      │
│                     │ (enum-backed)      │          │ mortgage_preapproved, evalu├─────────────────────┼────────────────────────────────────────────────────────────┤
│ decision_maker_mode │ VARCHAR            │ sí       │ valores: solo, couple, family                          │
│                     │ (enum-backed)      │          │                                                        │
└─────────────────────┴────────────────────┴──────────┴────────────────────────────
Nueva migración Alembic alembic/versions/0006_sprint2_1_buyer_profile_dimensions.py0005_sprint3_lead_conversation_link.py), corsibles vía op.add_column / op.drop_column.Verificar el mapeo ORM en infrastructure/repository.py (BuyerProfileRepository) par
Endpoints
                                                                                   No se agregan endpoints REST nuevos: la caponversacional que US-202–205 (extracción enqualification_flow.py, persistida vía BuyerProfileCaptureService.update_profile). Si app/modules/lead_qualification/api/schemas.py expone el perfil (ej. respuesta de estado de conversación), extender el schema de salida con financing_type y decision_maker_mode (nullable).
                                                                                   Archivos a modificar
                                                                                   - app/modules/lead_qualification/domain/modNSIONS, ProfilePatch, BuyerProfile.
- app/modules/lead_qualification/application/qualification_flow.py — nueva función extract_financing_and_decision_mode (keyworrón deextract_property_type/_TIMELINE_KEYWORDS).
- app/modules/lead_qualification/application/profile_capture.py — _snapshot().
- app/modules/lead_qualification/infrastruce columnas nuevas.
- app/modules/lead_qualification/api/schemas.py — si expone perfil, agregar campos.
- alembic/versions/0006_sprint2_1_buyer_profile_dimensions.py — nueva migración.
- tests/test_qualification_flow.py, tests/test_buyer_profile.py — casos nuevos.                           
Definition of Done                                                                                        
- [ ] Enums y campos agregados al dominio, sin romper ProfilePatch.is_empty() ni completeness() (deben itelas 7 dimensiones).
- [ ] Extractor de financiamiento/modo de decisión con keywords en español (contado, crédito hipotecario, crédito preaprobado, evaluando / solo, en pareja, con mi familia).                                                - [ ] Migración Alembic aplicada y reversibos con alembic upgrade head y alembicdowngrade -1).
- [ ] BuyerProfileRepository persiste y lee los dos campos nuevos.
- [ ] Tests unitarios: extracción exitosa, reprompt (si aplica), completeness() con 7 dimensiones, snapshocampos nuevos.
- [ ] Test de regresión: profiles existentes (creados antes de la migración) con financing_type=None no rocompleteness() ni el gate QA-14 (el umbral e al añadir dos dimensiones nuevas —documentar este efecto secundario en el proposal, puede requerir ajustar profile_completeness_threshold o las nuevas dimensiones del cálculo de gate ra bloqueantes).
- [ ] Documentación actualizada: openspec/specs/lead-qualification/ (nuevo o extendido spec para US-208), Documents/Oficial/HU_Calificacion_Recomenda no implementado]).

No-funcionales

- Seguridad/tenant isolation: el nuevo extractor debe llamar _assert_tenant igual que los extractores existentes.
- Observabilidad: ningún log nuevo requerido más allá de lo que ya cubre event_bus.publish para ProfileCompleted.
- Performance: extracción determinista por regex/keyword, sin llamada a LLM — sin impacto de latencia.
- Backward compatibility: perfiles pre-exisn seguir siendo válidos (None es un estadolegítimo, igual que las 5 dimensiones actuales antes de completarse).