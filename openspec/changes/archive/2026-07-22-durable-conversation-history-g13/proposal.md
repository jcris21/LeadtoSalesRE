## Why

`LangGraphResponder` (`app/modules/conversation_ownership/application/langgraph_responder.py`) checkpoints conversational turns with `InMemorySaver` by default, in production as well as in tests. A process restart wipes every active checkpoint: the LLM starts cold, re-greets the lead, and re-asks qualification dimensions already captured in earlier turns — observed live after the G11 deploy (re-asked property type already extracted in turn A2). This is tracked as gap **G13** in `docs/e2e-manual-chat-checklist.md` (line 65). The lead's `BuyerProfile` is unaffected (it lives in Postgres independently), but the conversational UX resets, which reads as the agent "forgetting" mid-conversation. Separately, `TurnState.messages` accumulates without bound (`operator.add`), which will inflate checkpoint payload size as conversations lengthen — worth fixing in the same pass since it touches the same state shape.

## What Changes

- Replace the production-default checkpointer with `AsyncPostgresSaver` (`langgraph-checkpoint-postgres`, backed by `psycopg` + `psycopg_pool` — a second Postgres driver alongside the existing asyncpg/SQLAlchemy engine, since there is no official asyncpg-based LangGraph checkpointer). Tests keep injecting `InMemorySaver` explicitly via the existing constructor seam — no change to test behavior.
- Checkpoint schema (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`) is created idempotently via `await AsyncPostgresSaver.setup()` at app boot — **no Alembic migration**, since the schema is library-owned and versioned by `langgraph-checkpoint-postgres` itself.
- Bound `TurnState.messages` to the last `conversation_history_window_turns` turns (new setting, default 12). Turns evicted from the window are folded into a deterministic, length-bounded `summary` string (no LLM call) persisted in the same checkpoint, so it is restart-safe too. The summary is prepended to the brain's history as a `system` message — `ConversationBrain.generate()`'s signature is unchanged.
- `LangGraphResponder.history()` surfaces the accumulated summary alongside the windowed messages.
- Async pool lifecycle (open, `setup()`, close) is bound to the FastAPI `lifespan` in `app/main.py`, next to the existing outbox/decay/crm background loops. If Postgres checkpointer init fails, the app degrades to `InMemorySaver` and logs an error instead of failing to boot (same degrade-not-crash pattern as G2/G4).
- New settings in `app/core/config.py`: `conversation_checkpointer` (`memory` | `postgres`, default `postgres`), `conversation_history_window_turns` (default `12`).
- New dependencies: `langgraph-checkpoint-postgres`, `psycopg[binary]`, `psycopg-pool`.

Out of scope: retrieval-on-demand from `archived_messages`/`ArchivedMessageORM` for references to conversation content older than the window — that table is populated independently from the Chatwoot webhook path already and is left untouched; on-demand recall is deferred to a separate future ticket.

## Capabilities

### New Capabilities
- `conversational-checkpoint-persistence`: durability and bounded size of the LangGraph conversational checkpoint — the checkpointer backend, the windowing/summary behavior of `TurnState`, and the restart-survival guarantee. Distinct from the existing `conversation-memory` capability, which covers structured signal extraction (style/family observations) into a separate `conversation_memory` table and does not touch the LangGraph checkpoint at all.

### Modified Capabilities
(none — no existing spec's requirements change; this introduces a new capability alongside them)

## Impact

- **Code**: `app/modules/conversation_ownership/application/langgraph_responder.py` (windowing, summary, saver lifecycle, `history()`), `app/main.py` (lifespan init/shutdown), `app/core/config.py` (new settings).
- **Dependencies**: `pyproject.toml` / `uv.lock` gain `langgraph-checkpoint-postgres`, `psycopg[binary]`, `psycopg-pool` — a second Postgres driver in the process alongside asyncpg.
- **Database**: new library-owned tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`) created at boot via `setup()`, not via Alembic. `alembic upgrade head` no longer fully describes the schema — must be documented for operators.
- **Connections**: a new, separate connection pool (psycopg) alongside the existing SQLAlchemy pool (`pool_size=10, max_overflow=10`); must stay small (2-5) and be accounted for against the Supabase connection cap.
- **Tests**: `tests/test_langgraph_responder.py` (windowing/summary unit tests, shared-`InMemorySaver` restart-simulation test — the actual regression test for the observed bug), new `tests/test_langgraph_responder_postgres.py` (`@pytest.mark.integration`, gated on reachable Postgres).
- **Docs**: `docs/e2e-manual-chat-checklist.md` — close G13, document the startup-DDL note.
