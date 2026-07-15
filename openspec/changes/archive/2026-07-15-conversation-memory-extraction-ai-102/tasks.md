## 1. Module scaffold

- [x] 1.1 Create `app/modules/conversation_memory/` with `domain/`, `application/`, `infrastructure/` packages (mirrors `lead_qualification`/`conversation_ownership` layout)

## 2. Domain model

- [x] 2.1 Add `MemoryType` enum (`STYLE_PREFERENCE`, `FAMILY_CONTEXT`, `TONE` — `TONE` is an enum placeholder only, no extractor branch in this change) to `domain/models.py`
- [x] 2.2 Add `ConversationMemoryObservation` entity (`id`, `conversation_id`, `lead_id`, `organization_id`, `memory_type: MemoryType`, `entity_name`, `value: dict`, `confidence: float`, `created_at`)

## 3. Extraction

- [x] 3.1 Add `extract_conversation_memory` to `application/memory_extraction.py`: returns a list of zero or more `ConversationMemoryObservation` (multiple signals per message allowed, unlike US-209's single-best-match)
- [x] 3.2 Spanish keyword table for `STYLE_PREFERENCE` (minimalista, luminoso, moderno, clásico, acogedor, elegante, rústico, contemporáneo)
- [x] 3.3 Spanish keyword table for `FAMILY_CONTEXT` (tenemos hijos, tenemos niños, vivimos solos, somos una pareja sin hijos, tenemos mascota)
- [x] 3.4 Fixed placeholder `confidence=0.6` per matched observation (design.md Decision 4)
- [x] 3.5 `_assert_tenant`-equivalent check before persisting (same tenant-isolation pattern as `qualification_flow.py`)

## 4. Persistence

- [x] 4.1 Add `ConversationMemoryORM` to `infrastructure/db_models.py` (table `conversation_memory`, schema per `AI_Recommendation_Domain_Model.md` §4)
- [x] 4.2 Add `ConversationMemoryRepository` (`add`, `list_for_lead`, `list_for_conversation`) to `infrastructure/repository.py`
- [x] 4.3 Add Alembic migration `0008_sprint2_1_conversation_memory.py` (down_revision `0007`) — create `conversation_memory` table, reversible `downgrade()`
- [x] 4.4 Register the new module's ORM models on `Base.metadata` via an import in `app/main.py` (no user-facing API router in this change) and `alembic/env.py`

## 5. Tests

- [x] 5.1 `tests/test_conversation_memory.py`: happy-path style-preference extraction
- [x] 5.2 `tests/test_conversation_memory.py`: happy-path family-context extraction
- [x] 5.3 `tests/test_conversation_memory.py`: both signals in one message insert two rows
- [x] 5.4 `tests/test_conversation_memory.py`: no-signal message inserts nothing
- [x] 5.5 `tests/test_conversation_memory.py`: tenant isolation rejected
- [x] 5.6 `tests/test_conversation_memory.py`: recording an observation does not change `BuyerProfile.completeness()` for the same lead

## 6. Documentation

- [x] 6.1 `specs/conversation-memory/spec.md` delta already drafted as part of this proposal (ADDED Requirements, new capability)
- [x] 6.2 Remove `[GAP — no implementado]` marker for AI-102 in `Documents/Oficial/HU_Calificacion_Recomendacion.md`, update the summary table row

## 7. Verification

- [x] 7.1 Verify migration `0008` chains correctly off `0007` (import + structural check, since no live Postgres is reachable in this sandbox — same caveat as US-208/US-209)
- [x] 7.2 Run full test suite (`pytest`) and confirm no regressions — `tests/test_conversation_memory.py` (6/6) plus the full qualification/recommendation regression batch all pass.
