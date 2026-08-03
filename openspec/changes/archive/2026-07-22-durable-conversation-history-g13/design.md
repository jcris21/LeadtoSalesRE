## Context

`LangGraphResponder` checkpoints one turn state (`TurnState`) per `thread_id = conversation_id`. Today the checkpointer is `InMemorySaver()`, both as the constructor default (`langgraph_responder.py:83`) and inside the process-wide singleton `get_default_responder()` (line 118-130). `CoordinatorAgent` resolves this singleton lazily per message (`coordinator.py:104-109`) and has no other coupling to the checkpointer.

Two independent constraints shape this design:
- **Driver mismatch**: the app's SQLAlchemy engine (`app/core/database.py`) is built on `asyncpg` (URL rewritten `postgresql://` → `postgresql+asyncpg://`). LangGraph's async Postgres checkpointer (`AsyncPostgresSaver`, package `langgraph-checkpoint-postgres`) is built on `psycopg` (v3) + `psycopg_pool`, not asyncpg. There is no official asyncpg-based checkpointer, so this change necessarily introduces a second Postgres driver into the process — it reuses the same database (`database_url`), not a second database.
- **Lifecycle mismatch**: `AsyncPostgresSaver` needs a live async connection pool opened via an async context manager plus a one-time `await setup()` call. The current singleton is built lazily and synchronously the first time a message arrives, which cannot host an async pool. The pool must instead be opened during the FastAPI `lifespan`, alongside the outbox/decay/crm background loops already started there (`app/main.py`).

The project's standing architectural position (`docker-compose.yml` header comment, `Documents/ExtraDocuments/RedisNotYeat.md`) is Postgres-only for internal state — no Redis, no broker — at this volume. This design stays inside that boundary.

## Goals / Non-Goals

**Goals:**
- A new `LangGraphResponder` instance on the same `thread_id` (i.e. a restarted process) rehydrates prior conversational context — this is the literal G13 acceptance criterion.
- Bound the size of the active checkpoint (`TurnState.messages`) so it does not grow unboundedly across a long conversation.
- Preserve conversational continuity beyond the window via a durable, bounded summary rather than silently dropping older turns.
- Degrade gracefully (fallback to `InMemorySaver`, log an error) if the Postgres checkpointer cannot initialize, rather than failing app boot.

**Non-Goals:**
- On-demand retrieval/recall of specific older messages when a lead references something outside the window (semantic search over `archived_messages`). Explicitly deferred — separate future ticket, own activation trigger.
- Any change to `ArchivedMessageORM` / the Chatwoot webhook archival path.
- Multi-replica/horizontal-scaling correctness for the checkpointer singleton. The current deployment is single-process; sharing one durable Postgres store across replicas is a natural consequence of this change but cross-replica routing/affinity is not designed or tested here.
- Any change to `BuyerProfile`/`PROFILE_DIMENSIONS` completeness logic or to the unrelated `conversation-memory` capability (structured signal extraction) — different table, different concern, coincidentally similar name.

## Decisions

**D1 — `AsyncPostgresSaver` (psycopg) over alternatives, reusing `database_url`.**
Alternatives considered: (a) Redis-backed checkpointer — rejected, contradicts the standing no-Redis decision at this volume, and durability was the actual gap, not latency; (b) a hand-rolled checkpointer writing into an existing SQLAlchemy/asyncpg-managed table — rejected, would require re-implementing checkpoint serialization semantics LangGraph already solves, and diverges from the library's own schema evolution. Chosen: the official `langgraph-checkpoint-postgres` package against the same database, accepting the second-driver cost as the smallest deviation from existing infrastructure.

**D2 — Checkpoint schema created via `setup()` at boot, not an Alembic migration.**
The checkpoint schema (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`) is owned and versioned by `langgraph-checkpoint-postgres` itself, which tracks its own `checkpoint_migrations` table across package releases. Hand-porting that DDL into an Alembic revision would create a second, divergent source of truth every time the package upgrades. `setup()` is idempotent and safe to call on every boot. Trade-off accepted: `alembic upgrade head` no longer fully describes the database schema — documented explicitly in `docs/e2e-manual-chat-checklist.md` and in the responder module docstring so operators aren't misled. Alembic's autogenerate (against `Base.metadata`) will not propose dropping these tables because they are never registered as SQLAlchemy models — verified against `alembic/env.py`.

**D3 — Windowing + summary computed inside the node, not via a channel reducer.**
`TurnState.messages` currently uses `Annotated[list, operator.add]`, an append-only reducer that can only grow the channel. Truncation requires shrinking it, and computing the evicted-turns summary requires knowing exactly which messages are being dropped — information only available at the point of truncation. Both needs are satisfied by moving `messages` to a plain replace-channel and doing concatenation + truncation inside `_respond_node`, which returns the already-windowed list plus the updated `summary`.

**D4 — Summary is deterministic (no LLM call), folded incrementally, length-capped.**
Consistent with the existing `TemplateBrain` philosophy of a fully offline-capable pipeline. A simple, testable fold function (`_fold_summary(existing_summary, dropped_messages) -> str`) appends compact per-turn lines and caps total length, so the summary itself never grows unboundedly even across very long conversations.

**D5 — Summary reaches the brain as a prepended system message, not a `ConversationBrain.generate()` signature change.**
Alternative considered: add a `summary: str = ""` kwarg to the `ConversationBrain` Protocol. Rejected in favor of prepending `{"role": "system", "content": summary}` to the `history` list passed to `generate()`, because it requires zero changes to `TemplateBrain`, `LLMConversationBrain`, or the `RecordingBrain` test double — the existing `generate(self, *, system_prompt, history, text)` contract is untouched.

**D6 — Fail-open on checkpointer init failure.**
If `AsyncPostgresSaver` initialization fails at boot (connectivity, credentials, package/version mismatch), the app logs the error and falls back to constructing the responder with `InMemorySaver`, matching the degrade-not-crash pattern already used for the Gemini-key-optional paths (G2, G4). Boot must not hard-fail on this dependency.

## Risks / Trade-offs

- **[Risk] Second Postgres driver (psycopg) increases dependency and connection-budget surface next to the existing asyncpg engine.** → Mitigation: keep the psycopg pool small (2-5 connections), document the combined connection budget against the Supabase plan cap, and pin `langgraph-checkpoint-postgres`/`psycopg`/`psycopg-pool` versions verified compatible with the installed `langgraph` version via `uv add` resolution (not guessed).
- **[Risk] `setup()`-at-boot DDL means `alembic upgrade head` alone no longer describes the full schema, which could surprise an operator restoring from a fresh DB.** → Mitigation: explicit documentation in the E2E checklist and module docstring; `setup()` is idempotent so it self-heals on next boot regardless of order relative to Alembic.
- **[Risk] Windowing regresses an existing test asserting full-history resumption across turns (if any relies on unbounded growth).** → Mitigation: default window (12 turns / 24 messages) exceeds the 8-dimension qualification script length observed in the E2E checklist; existing resumption tests are re-verified against the new bound as part of this change, not assumed compatible.
- **[Risk] TLS/truststore behavior may differ between asyncpg (patched via `truststore.inject_into_ssl()` in `app/main.py`) and psycopg's own connection path**, especially relevant given this environment's TLS-interception constraints. → Mitigation: verify psycopg connections succeed against the Supabase host in this environment before merging; configure `sslmode` explicitly if the stdlib SSL context patch does not apply to psycopg.
- **[Trade-off] Deterministic summary is lossier than an LLM-generated summary** (no paraphrase/compression intelligence, just concatenated compact lines). Accepted because it keeps the pipeline credential-free by default and avoids adding LLM cost/latency to every truncation event; an LLM-backed summarizer can replace `_fold_summary` later behind the same function boundary without touching the rest of the design.

## Migration Plan

1. Ship dependency + settings changes (default `conversation_checkpointer=postgres`) behind the existing fail-open behavior (D6) — a deploy with no reachable checkpoint DB still boots, just without durability, identical to today's behavior.
2. Deploy; first boot runs `setup()` and creates the checkpoint tables idempotently.
3. Verify via the restart-simulation test in a staging-like environment before relying on it in the E2E checklist (G13 closure).
4. Rollback: set `conversation_checkpointer=memory` to revert to current (pre-change) in-memory behavior without a code rollback, if the Postgres checkpointer misbehaves in production.

## Open Questions

- Exact compatible version pins for `langgraph-checkpoint-postgres` / `psycopg` / `psycopg-pool` against the installed `langgraph>=1.2.8` — to be resolved via `uv add` during implementation, not guessed here.
- Whether psycopg's TLS handling needs an explicit `sslmode`/cert configuration in this environment, or inherits the same effective trust store as asyncpg — to be verified during implementation against the actual Supabase connection.
- Final default for `conversation_history_window_turns` (proposed 12) — validate against real E2E script length once G13 closure testing runs end-to-end.
