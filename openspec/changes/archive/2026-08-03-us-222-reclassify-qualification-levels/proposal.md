## Why

US-217 ordered `PROFILE_DIMENSIONS` so the six signals `LeadReadinessService` (US-214)
weights (`budget`, `locations`, `property_type`, `timeline`, `financing_type`,
`decision_maker_mode`) block the recommendation, while `must_haves`, `bedrooms`, and
`motivation` (US-219) were treated as post-recommendation refinement. In practice this
means a lead can reach the Top-3 recommendation without the platform ever having asked a
hard-filter-relevant signal (`bedrooms`) or a search-refinement signal (`must_haves`,
`motivation`), while `timeline`/`financing_type`/`decision_maker_mode` — none of which
`StructuredFilterService` or `SemanticRetrievalService` consume today — gate the search
the lead actually wants. The dimensions that decide *what properties come back* were
Nivel 2; the dimensions that decide *how ready the lead is to transact* were Nivel 1. This
change inverts that: dimensions the search pipeline consumes become the blocking
Nivel 1 set, and financing/timeline/decision-maker signals — genuinely useful for sales
follow-up but irrelevant to which properties match — move to a new post-selection
Nivel 2 follow-up turn.

## What Changes

- Reorder `PROFILE_DIMENSIONS` (`app/modules/lead_qualification/domain/models.py`) to
  Nivel 1 = `budget, locations, property_type, bedrooms, motivation, must_haves`,
  Nivel 2 = `timeline, financing_type, decision_maker_mode`. `must_haves` keeps its
  existing field/column/API name — no rename to "amenities".
- **BREAKING (internal contract only, no DB schema change)**: split the combined
  `extract_timeline_and_must_haves` extractor (`qualification_flow.py`) into two
  independent extractors, `extract_timeline` and `extract_must_haves`, so
  `_DETERMINISTIC_EXTRACTORS` can give them genuinely different precedence
  (`must_haves` Nivel 1, `timeline` Nivel 2) instead of a single combined call.
  `_DETERMINISTIC_EXTRACTORS` is reordered to match the new Nivel 1 → Nivel 2 split.
- `bedrooms` becomes a real hard filter in `app/modules/recommendation/application/retrieval.py`'s
  structured-filter path (today it filters only on `budget`/`locations`/`property_type`) — this
  is the first time `bedrooms` participates in the SQL `WHERE` filtering `hybrid-retrieval`
  already performs for budget/locations/property_type. **`properties`/`PropertyORM` has no
  `bedrooms` column today** — this requires a new Alembic migration adding
  `properties.bedrooms` (nullable `Integer`, absent = no filter clause, same "absent
  constraint = no clause" contract as `Property.matches_hard_filters`'s existing fields),
  plus threading the field through `Property`, `matches_hard_filters`, the
  `PropertyLookup.filter_candidates` Protocol, and `PropertyRepository`'s SQL `WHERE`.
- `must_haves` keeps feeding the existing pgvector semantic-similarity scoring
  (`embedding_model.py`/`ranking_engine.py`) that already refines the structured-filter
  candidate set — only its `PROFILE_DIMENSIONS` classification changes, not its retrieval
  behavior.
- New deterministic follow-up turn (new module, sibling to `deepening_turn.py`/
  `scheduling_turn.py`) that asks the lead for the first missing Nivel 2 dimension
  (`timeline`, `financing_type`, `decision_maker_mode`) — gated on
  `DeepeningTurnResult.outcome == "selected"` from US-220's deepening turn, i.e. only after
  the recommendation has been shown AND the lead has confirmed interest in a specific
  Top-3 property. Never blocks scheduling; same short-circuit/`ResponderPort` contract as
  the existing turns.
- `LeadReadinessService.compute_readiness_score` (`lead_readiness.py`, US-214) is remapped
  to weight the new Nivel 1 set (`budget, locations, property_type, bedrooms, motivation,
  must_haves`) instead of the old one, with new weights summing to 100.
  `classify_financing_readiness` is left unchanged — it is a financing-specific
  classification (cash/mortgage + urgency + zone) that stays meaningful regardless of
  which dimensions block the completeness gate.
- No changes to `CompletenessGate`/`profile_completeness_threshold` (US-215) mechanics —
  same 65% threshold, same `missing_dimensions()[0]`-driven directed question, just over
  the new dimension order.

## Capabilities

### New Capabilities
- `qualification-followup-turn`: deterministic post-selection turn that asks for the
  first missing Nivel 2 dimension (`timeline`, `financing_type`, `decision_maker_mode`)
  once the lead has selected a specific recommended property.

### Modified Capabilities
- `lead-qualification-flow`: `PROFILE_DIMENSIONS` Nivel 1/Nivel 2 split changes (US-217
  reversed for `bedrooms`/`motivation`/`must_haves` vs `timeline`/`financing_type`/
  `decision_maker_mode`); the combined timeline/must-haves capture requirement splits
  into two independent requirements.
- `hybrid-retrieval`: structured filtering gains `bedrooms` as an additional SQL `WHERE`
  hard-filter dimension alongside budget/locations/property_type.

## Impact

- Affected code: `app/modules/lead_qualification/domain/models.py`,
  `app/modules/lead_qualification/application/qualification_turn.py`,
  `app/modules/lead_qualification/application/qualification_flow.py`,
  `app/modules/lead_qualification/application/lead_readiness.py`,
  `app/modules/recommendation/domain/models.py` (`Property.bedrooms`,
  `matches_hard_filters`), `app/modules/recommendation/infrastructure/db_models.py`
  (`PropertyORM.bedrooms`), `app/modules/recommendation/infrastructure/repository.py`
  (SQL `WHERE`), `app/modules/recommendation/application/retrieval.py`
  (`PropertyLookup.filter_candidates` signature), a new
  `alembic/versions/xxxx_properties_bedrooms.py` migration,
  `app/modules/conversation_ownership/application/coordinator.py`, and a new follow-up
  turn module under `app/modules/conversation_ownership/application/`.
- Affected tests: `test_buyer_profile.py`, `test_qualification_flow.py`,
  `test_coordinator_qualification_turn.py`, `test_recommendation_service.py`,
  `test_ranking_engine.py`, `test_hybrid_retrieval.py`, plus a new test module for the
  follow-up turn.
- Affected docs: `Documents/Oficial/HU_Calificacion_Recomendacion.md`, the Nivel 1/Nivel 2
  comment block in `models.py`.
- One new Alembic migration: `properties.bedrooms` (nullable `Integer`). No other schema
  change — `must_haves` keeps its existing name/column, no API contract change, no new
  dependencies.
- Supersedes US-217's dimension ordering rationale (comment block in `models.py`
  referencing `LeadReadinessService`'s six weighted signals as Nivel 1) — that mapping no
  longer holds and is replaced by the search-pipeline-driven rationale above.
