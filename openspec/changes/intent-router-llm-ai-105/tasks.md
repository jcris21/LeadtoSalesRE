## 1. Coordinator wiring

- [x] 1.1 `_classify_intent` returns `IntentCategory | None` instead of `None` on success
      (still `None`/swallowed on failure — unchanged failure contract).
- [x] 1.2 `handle_message` captures the returned category and threads it into
      `_conversational_turn`.
- [x] 1.3 Add `KnowledgeAnswererPort` protocol + constructor-injectable
      `knowledge_answerer` param on `CoordinatorAgent`, default-wired to real `KnowledgeService`
      + `build_default_query_embedder(get_settings().gemini_api_key)`.
- [x] 1.4 Add `_knowledge_turn` helper: calls `KnowledgeAnswererPort.answer` only for
      `objecion`/`pregunta_informativa`; returns `None` on `found=False` or any exception
      (swallowed, logged); records `knowledge.answer` tool call on the trace only when it fires.
- [x] 1.5 Insert the branch in `_conversational_turn` between the default responder call and the
      existing reprompt/ask_identity override checks (knowledge answer sits below both, per
      design.md precedence table).

## 2. Tests

- [x] 2.1 Regression: existing `tests/test_coordinator_qualification_turn.py`,
      `tests/test_coordinator.py`, `tests/test_coordinator_identity_gate.py`,
      `tests/test_coordinator_grounding_note.py`, `tests/test_coordinator_scheduling_turn.py` all
      pass unmodified.
- [x] 2.2 New test: objection message + stub `KnowledgeAnswererPort` returning `found=True` →
      reply equals the knowledge answer text; `LeadObjectionORM` is still recorded (both paths
      fire independently).
- [x] 2.3 New test: `pregunta_informativa` message + stub answerer `found=True` → reply equals
      the knowledge answer.
- [x] 2.4 New test: objection message + stub answerer `found=False` → reply falls back to the
      default responder's output (today's behavior, unchanged).
- [x] 2.5 New test: stub answerer raises → reply falls back to the default responder's output,
      no exception propagates, turn completes.
- [x] 2.6 New test: non-consuming category (e.g. `qualification`/`otro`) → stub answerer's
      `answer` is never called.
- [x] 2.7 New test: `ask_identity`/qualification reprompt still override a would-be knowledge
      answer (precedence order preserved).

## 3. Verification

- [x] 3.1 Run the touched/new test files with the shared venv's pytest.
- [x] 3.2 Run the full suite with `-m "not integration"` to confirm no regressions.
- [x] 3.3 Mark all tasks above done.
