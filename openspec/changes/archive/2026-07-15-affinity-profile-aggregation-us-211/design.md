## Context

AI-102 (Sprint 2.1, archived change `conversation-memory-extraction-ai-102`) established the `conversation_memory` table and a deterministic extractor (`extract_conversation_memory`) that inserts append-only `ConversationMemoryObservation` rows (`memory_type` ∈ {`style_preference`, `family_context`}, `value` jsonb, fixed `confidence = 0.6`). Nothing consumes those rows yet. `buyer_profiles` (lead_qualification module) holds the 7 closed-enum/range dimensions; `leads` mirrors wacrm and carries scoring/classification fields. US-211 adds the synthesis step: two jsonb snapshots with distinct owners — `buyer_profiles.ai_profile` (Ranking Engine signal) and `leads.buyer_persona` (Coordinator tone signal).

Constraints inherited from the codebase:

- Portable `JSON` column type (not Postgres `JSONB` import) so the aiosqlite test harness keeps working — same convention as `buyer_profiles.locations` and `conversation_memory.value`.
- Tenant isolation via `_assert_tenant` (lead must belong to `organization_id`, else `LeadNotFoundError`) — same as `memory_extraction.py` and `qualification_flow.py`.
- Deterministic, no-LLM first cut — consistent with AI-102 and the qualification extractors.

## Goals / Non-Goals

**Goals:**

- Synthesize `conversation_memory` rows (confidence ≥ threshold) into `ai_profile` and `buyer_persona` snapshots.
- Make `ai_profile` available as a Ranking Engine input signal (Sprint 2.2 Definition of Done) — availability only; wiring into `WeightedRankingEngine` is US-305's job.
- Recompute only when observations change (caller invokes the aggregator after a non-empty extraction), never on the search/read path.
- Keep the two snapshots strictly independent: separate writers, separate consumers, no cross-overwrite.

**Non-Goals:**

- No LLM-backed inference (future iteration, same posture as AI-102).
- No scheduler/cron/background job — recompute is synchronous, post-extraction.
- No changes to `PROFILE_DIMENSIONS`, `completeness()`, or the QA-14 gate.
- No Ranking Engine changes (US-305) and no Coordinator (AI-104).
- No new API endpoints.

## Decisions

**D1 — Service lives in `conversation_memory/application/profile_aggregation.py`.** The HU allows "síntesis dentro de Qualification Flow o servicio propio". Own service in the conversation_memory module wins: the input data (observations) is owned there, the module already imports lead_qualification's repository for tenant checks (established direction of dependency), and qualification_flow.py is already 400+ lines of extractors with a different responsibility (message → patch, not rows → snapshot).

**D2 — Eligibility threshold `_MIN_CONFIDENCE = 0.5` as module constant.** Below AI-102's fixed 0.6 keyword confidence so current observations qualify, while pre-filtering any future low-confidence LLM output. Not config — no other extractor threshold is configurable in the codebase; promote to config when a second consumer needs a different cut.

**D3 — Deterministic score derivation.** `ai_profile` scores are normalized keyword-frequency ratios over eligible observations, weighted by observation confidence:
- `modern_score`: `count(modern-family adjectives) / count(all style adjectives observed)`. The AI-102 extractor's `_STYLE_KEYWORDS` has 8 base adjectives (gender variants aside): `moderno`, `contemporaneo`, `minimalista`, `luminoso`, `elegante` (the "modern" family — numerator) and `clasico`, `acogedor`, `rustico` (denominator-only: they count toward "all style adjectives observed" but never toward the modern-family numerator, so their presence dilutes `modern_score` toward 0 without needing a symmetric "classic" pole). This is a deliberate two-bucket split, not an omission — a lead who only ever says "acogedor" and "rustico" gets `modern_score = 0.0`, `observation_count > 0`, which the Ranking Engine reads as "not modern" without requiring a second score. Revisit if US-305 needs a positive classic-affinity signal distinct from "absence of modern."
- `family_score`: presence-weighted signal from `family_context` observations. Positive signal from children-presence phrases (`tenemos/tengo hijos/hijas`, `tenemos/tengo ninos/ninas`, `tengo un hijo`, `tengo una hija` — AI-102's `_FAMILY_CHILDREN_PRESENCE_KEYWORDS`); explicit no-children phrases (`no tenemos/tengo hijos`, `sin hijos`, `somos una pareja sin hijos` — `_FAMILY_NO_CHILDREN_KEYWORDS`) push it down. `_FAMILY_SOLO_KEYWORDS` (`vivo/vivimos solo/a/os/as`) and `_FAMILY_PET_KEYWORDS` are family-context signals but do not move `family_score` — they feed `buyer_persona.has_pets` (D4) instead.
- `confidence`: mean confidence of the observations used; `observation_count` and `computed_at` (ISO-8601 UTC) for provenance.
Shape follows `AI_Recommendation_Domain_Model.md` §"Uso de JSONB" (`modern_score`/`family_score`/`confidence`), extended with provenance keys. Alternative (embedding-based affinity) rejected: US-308 hasn't landed a real embedding model yet.

**Open item — household size/composition not captured.** Neither `ai_profile` nor `buyer_persona` currently captures children count or age, even though that's a stronger bedroom-count signal than the boolean `family_stage` enum in D4. AI-102's keyword extractor has no numeral/age parsing (`_FAMILY_CHILDREN_PRESENCE_KEYWORDS` only detects presence, not "cuántos"/"qué edad"). Adding it would mean: (a) a new deterministic pattern in `memory_extraction.py` (e.g. `\b(un|una|dos|tres|\d+)\s+(hijo|hija|hijos|hijas)\b` plus an optional age clause), (b) a new `entity_name`/value shape in `ConversationMemoryObservation` (or a new `MemoryType`), and (c) a decision on whether count/age lives in `ai_profile` (Ranking Engine — room-count signal) or a new field entirely, since `buyer_profiles.must_haves` (existing PROFILE_DIMENSIONS) may already be the intended home for "necesito 3 habitaciones" rather than a derived inference from family size. Out of scope for this change; flag as a follow-up US once there's evidence leads state family size/ages in free text often enough to justify the parser.

**D4 — `buyer_persona` derivation is categorical, not scored.** `{"family_stage": "family_with_children" | "couple_no_children" | null, "has_pets": bool, "communication": "whatsapp", "computed_at": ...}`. `communication` is constant `"whatsapp"` for now (only channel in the product); `family_stage`/`has_pets` map from `family_context` phrases. Tone-based keys wait for the `MemoryType.TONE` extractor (enum value exists, extractor doesn't).

**D5 — Missing `buyer_profile` row degrades gracefully.** If the lead has no `buyer_profiles` row yet (profile capture hasn't run), the aggregator still writes `leads.buyer_persona` and skips `ai_profile` silently, returning a result object that reports which snapshots were written. It does NOT create a `BuyerProfile` — that's `BuyerProfileCaptureService`'s exclusive job.

**D6 — Recompute trigger is the caller's contract, not an event bus.** `aggregate()` is invoked by whoever just called `extract_conversation_memory` and got a non-empty list (today: tests / future Coordinator; the two calls compose in the same session/transaction). Alternatives rejected: DB trigger (logic in Python per repo convention), SQLAlchemy event listener (hidden coupling), polling (violates "not on every search").

**D7 — Idempotent overwrite semantics.** Each run recomputes the snapshot from the full eligible observation set and overwrites the column (last-write-wins within its own column). No merge with previous snapshot — observations are append-only, so the full set is always available and recomputation is pure.

## Risks / Trade-offs

- [Keyword-frequency scores are crude] → Documented as first-cut provenance (`confidence` ≤ 0.6 signals deterministic origin); the shape is stable so an LLM-backed scorer can swap in without schema change (same posture AI-102 took for extraction).
- [Aggregate on every extraction could get chatty for very active leads] → Bounded: one SELECT over an indexed `lead_id` plus two UPDATEs, only on messages that actually produced observations; acceptable at MVP volume.
- [Two writers to `leads` (Lead Sync Adapter is documented as sole writer)] → `buyer_persona` is a net-new column never sourced from wacrm; CON-2 (wacrm as SoR) covers CRM-mirrored fields only. Documented in the migration and ORM docstrings, mirroring the `lead_score`/`lead_classification` precedent (US-209 already writes those).
- [SQLite `JSON` vs Postgres `jsonb` drift] → Same accepted trade-off as every existing JSON column in the repo.

## Migration Plan

1. Alembic `0009_sprint2_2_affinity_profile`: `op.add_column("buyer_profiles", sa.Column("ai_profile", sa.JSON(), nullable=True))` and `op.add_column("leads", sa.Column("buyer_persona", sa.JSON(), nullable=True))`. Downgrade drops both. Nullable columns → no backfill, no downtime, instantly reversible.
2. Deploy code (service is additive; nothing calls it until a caller composes extraction + aggregation).
3. Rollback = revert migration + code; no data loss risk (snapshots are derived, recomputable from `conversation_memory`).

## Open Questions

- None blocking. Score-family taxonomy (which adjectives map to which score) is intentionally minimal; extending it is additive.
