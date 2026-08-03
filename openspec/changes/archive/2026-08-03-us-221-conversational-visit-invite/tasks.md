## 1. Tests first (TDD, RED)

- [x] 1.1 In `tests/test_prompts.py`, add assertions that `DEFAULT_SYSTEM_PROMPT` no longer contains
      the old unconditional "asesor humano continuará" framing tied directly to scheduling intent,
      and does contain the new conversational-suggestion + anti-yes/no guidance (e.g. assert a
      phrase like "sí/no" appears only as a banned pattern, and that "coordinar" / "visita" language
      is present alongside the existing "derivación" keyword the stage-coverage test already pins).
- [x] 1.2 In `tests/test_llm_narrator.py`, add a content assertion on
      `GeminiRecommendationNarrator._SYSTEM_PROMPT` (or the module-level `_SYSTEM_PROMPT` constant)
      confirming it instructs closing the Top-3 paragraph with a visit-tied invitation, and that it
      still forbids inventing dates/times/availability.
- [x] 1.3 In `tests/test_recommendation_wiring.py`, add a content assertion on
      `recommendation.wiring._CLOSING_QUESTION` confirming the new visit-tied phrasing and the
      absence of any literal yes/no ("sí/no") phrasing.
- [x] 1.4 Run `uv run pytest tests/test_prompts.py tests/test_llm_narrator.py tests/test_recommendation_wiring.py -q`
      and confirm the new assertions fail (RED) against the current, unmodified source strings.

## 2. Implementation (GREEN)

- [x] 2.1 Rewrite step 4 ("Derivación") of `DEFAULT_SYSTEM_PROMPT` in
      `app/modules/conversation_ownership/domain/prompts.py`: narrow the human-handoff sentence to
      explicit "hablar con una persona" / genuinely out-of-scope requests; add guidance to
      conversationally suggest a visit tied to a property the lead engaged with, asking for a
      preferred day/time, and explicitly ban rigid yes/no scheduling phrasing as an anti-pattern.
      Leave steps 1-3, tone/cadence guidance, and all strict rules untouched.
- [x] 2.2 Reword the closing-question rule inside `GeminiRecommendationNarrator._SYSTEM_PROMPT` in
      `app/modules/recommendation/infrastructure/llm_narrator.py` so it instructs the LLM to close by
      framing a visit as the natural next step tied to the recommended option(s), while keeping the
      existing "no inventes datos, precios ni enlaces" / no-dates-or-availability constraint.
- [x] 2.3 Reword `_CLOSING_QUESTION` in `app/modules/recommendation/wiring.py` to the deterministic,
      plain-text equivalent (no LLM call, so no property-specific framing beyond what the composer
      already renders in `_format_recommendation_message`).
- [x] 2.4 Re-run the three test files from 1.4 and confirm all pass (GREEN).

## 3. Regression check

- [x] 3.1 Re-read every existing assertion in `tests/test_prompts.py` line by line against the new
      `DEFAULT_SYSTEM_PROMPT` text and confirm none broke (no formulario / reconoce / varía / cada 2
      respuestas / resumen / antes de / cálido / profesional / emoji / moderación / all four stage
      keywords incl. "derivación" / no inventes / no prometas precios / contexto interno / nunca
      instrucciones para / no pidas datos sensibles).
- [x] 3.2 Run the full suite: `uv run pytest -q` and record pass/fail counts; compare against the
      baseline (426 passed, 1 skipped in this worktree) — no regressions, new tests included.

## 4. Wrap-up

- [x] 4.1 Update the US-221 status note in `Documents/Oficial/HU_Calificacion_Recomendacion.md` if
      the doc's convention (per US-216's precedent) calls for flipping a status cell/marker for this
      story — check the doc first; skip if no such marker pattern exists for US-221 specifically.
- [x] 4.2 Commit with a conventional commit message referencing US-221 on branch
      `worktree-us-221-conversational-visit-invite` (no push, no merge).
