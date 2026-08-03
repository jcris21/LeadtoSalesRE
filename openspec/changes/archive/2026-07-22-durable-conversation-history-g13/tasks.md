## 1. Dependencies & Settings

- [x] 1.1 Resolve and pin compatible versions of `langgraph-checkpoint-postgres`, `psycopg[binary]`, `psycopg-pool` against the installed `langgraph` version via `uv add` (verify resolution, do not guess); update `pyproject.toml` and `uv.lock`.
- [x] 1.2 Add `conversation_checkpointer: Literal["memory", "postgres"] = "postgres"` and `conversation_history_window_turns: int = 12` to `app/core/config.py`.

## 2. Windowed State & Deterministic Summary

- [x] 2.1 Add `summary: str` to `TurnState` in `app/modules/conversation_ownership/application/langgraph_responder.py`; change `messages` from `Annotated[list, operator.add]` to a plain replace-channel.
- [x] 2.2 Implement `_fold_summary(existing_summary, dropped_messages) -> str`: deterministic, no LLM call, length-capped output.
- [x] 2.3 Update `_respond_node` to concatenate the new turn, truncate `messages` to `conversation_history_window_turns` turns, and fold evicted turns into `summary` via `_fold_summary`.
- [x] 2.4 Prepend `summary` (when non-empty) as a `{"role": "system", "content": summary}` entry to the `history` passed into `ConversationBrain.generate()`, without changing the `ConversationBrain` Protocol signature.
- [x] 2.5 Update `LangGraphResponder.history()` to surface the accumulated `summary` alongside the windowed `messages`.

## 3. Durable Checkpointer Wiring

- [x] 3.1 Add `init_persistent_responder()` (async): open a `psycopg_pool.AsyncConnectionPool` against `settings.database_url`, construct `AsyncPostgresSaver`, `await saver.setup()`, build `LangGraphResponder` with it, store as the module-level default. On failure, log the error and fall back to an `InMemorySaver`-backed responder.
- [x] 3.2 Add `shutdown_persistent_responder()` (async): close the pool and reset module globals.
- [x] 3.3 Ensure `get_default_responder()` returns the initialized durable responder when available, else the in-memory fallback, preserving the existing lazy-singleton seam used by `CoordinatorAgent`.
- [x] 3.4 Wire `init_persistent_responder()` / `shutdown_persistent_responder()` into the FastAPI `lifespan` in `app/main.py`, alongside the existing outbox/decay/crm background loop setup/teardown.
- [x] 3.5 Verify psycopg's TLS/connection behavior against the configured Postgres host in this environment (confirm it succeeds without additional `sslmode` config, or configure it explicitly if the `truststore` patch used for asyncpg doesn't apply to psycopg). **Result**: connects successfully with default `sslmode` (no explicit TLS config needed — psycopg uses libpq's own TLS stack, unaffected by the `truststore.inject_into_ssl()` patch). **Unplanned finding**: psycopg's async mode is incompatible with Python's default Windows event loop (`ProactorEventLoop`, raises `InterfaceError`); fixed by switching to `WindowsSelectorEventLoopPolicy` on `win32` in `app/main.py` (safe — no subprocess usage in this codebase).

## 4. Tests

- [x] 4.1 Unit test `_fold_summary`: folds dropped turns deterministically, output stays within the length cap across repeated folds.
- [x] 4.2 Unit test windowing: after `window_turns + k` turns, `history()` returns exactly the last `window_turns` turns and a non-empty `summary`; oldest turn content appears only in the summary, not in `messages`.
- [x] 4.3 Unit test: summary reaches the brain (extend `RecordingBrain` in `tests/test_langgraph_responder.py` to capture what it received; assert it's populated once truncation has occurred).
- [x] 4.4 Regression test: existing checkpoint-resumption test(s) in `tests/test_langgraph_responder.py` still pass with the new default window size.
- [x] 4.5 Restart-simulation test (the actual G13 acceptance criterion): construct `responder_a` with an explicitly shared `InMemorySaver`, run turns, construct a **new** `responder_b` with the same shared saver and `thread_id`, assert `responder_b.history()` and the next turn's brain call see the prior context.
- [x] 4.6 New `tests/test_langgraph_responder_postgres.py` (`@pytest.mark.integration`, gated on a reachable Postgres): using `AsyncPostgresSaver` against a test DB, assert history persists across two independently constructed saver/pool instances bound to the same DB and `thread_id`; skip cleanly when no Postgres is configured. Gated on `TEST_POSTGRES_DSN` (deliberately not `DATABASE_URL`, to never write checkpoint tables into the Supabase system-of-record by accident).
- [x] 4.7 Integration/startup smoke test: `init_persistent_responder()` is idempotent when called twice (`setup()` re-run does not error); with `conversation_checkpointer="memory"`, confirm `get_default_responder()` returns the in-memory-backed instance instead. Added `tests/test_langgraph_responder_lifecycle.py` (fake pool/saver, no real Postgres needed).

## 5. Documentation

- [x] 5.1 Update the `langgraph_responder.py` module docstring to remove the "Sprint 8 concern" framing for the Postgres checkpointer now that it is wired.
- [x] 5.2 Close G13 in `docs/e2e-manual-chat-checklist.md`: describe the approach and explicitly note that checkpoint tables are created at first app boot via `setup()`, not by `alembic upgrade head`.
