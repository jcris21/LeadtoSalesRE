## Context

`DEFAULT_SYSTEM_PROMPT` (`app/modules/conversation_ownership/domain/prompts.py`) is the Coordinator's
fallback system prompt, sent verbatim on every turn across greeting/qualification/recommendation/
handoff whenever no per-organization prompt is published in the Prompt Registry
(`CoordinatorAgent._load_system_prompt`). Its step 4 ("Derivación") currently reads: *"si el lead
pide hablar con una persona, quiere agendar una visita o plantea algo fuera de tu alcance, indícale
que un asesor humano continuará la conversación."* That sentence predates US-212. US-212 (already
merged into this branch) wired `run_scheduling_turn` into `CoordinatorAgent._scheduling_turn`
(coordinator.py ~line 468-487): while `conversation.state is ConversationState.RECOMMENDATION`, any
lead message carrying a deterministically recognizable date+time (`extract_confirmed_slot`) now
triggers `SchedulingService.book_visit` directly — no human in the loop — and short-circuits the
LLM's reply with a deterministic confirmation/fallback message. The prompt's "quiere agendar ->
asesor humano" framing is therefore stale: it describes a handoff that no longer happens for the
common case, and it never told the LLM to proactively *invite* a visit in the first place — the only
existing invitation-adjacent language is the Top-3 delivery's closing question, which is open-ended
but not visit-specific.

US-221 (`Documents/Oficial/HU_Calificacion_Recomendacion.md:990-1011`) was explicitly gated on US-212
for this reason ("no hay horarios reales que redactar en lenguaje natural sin el wiring de
scheduling") — that gate is now open.

## Goals / Non-Goals

**Goals:**
- Make `DEFAULT_SYSTEM_PROMPT`'s scheduling-invitation language match reality: the assistant itself
  proposes a visit conversationally, tied to a specific property, instead of promising a handoff
  that the real code path no longer performs for the common case.
- Ban the rigid yes/no framing ("¿desea agendar? sí/no") as an explicit anti-pattern in the prompt,
  mirroring how the prompt already bans hallucinated properties/prices.
- Extend the same conversational-suggestion framing to the Top-3 delivery's closing language
  (`llm_narrator.py` system prompt and `wiring.py`'s deterministic `_CLOSING_QUESTION` fallback) so
  both surfaces are consistent.
- Preserve every existing safety rule verbatim in substance: anti-hallucination, no-promised-
  availability, no-sensitive-data, prompt-injection guard, and every keyword `tests/test_prompts.py`
  already pins.

**Non-Goals:**
- No dependency on US-220 (the deepening turn that would identify "the option the lead showed
  interest in" as a first-class signal). US-220 is being built in parallel in a sibling worktree and
  is not merged into this branch. This change uses only property references already available today:
  the Top-3 just delivered, or a property the lead named earlier in the conversation history the LLM
  already has access to via the LangGraph checkpoint.
- No change to `run_scheduling_turn`, `extract_confirmed_slot`, `AvailabilityValidatorService`, or
  `SchedulingService` — the automatic booking path, the slot-recognition grammar, and the
  availability-check gate (Regla 1, Agentic_System.md §1.B) are already correct and untouched; this
  change is copy-only, layered on top of that existing orchestration step.
- No new DB column/table, no new LangGraph node, no new `AIDecisionTrace` requirement — a prompt
  string is not a new decision point in the graph.

## Decisions

**Decision 1 — Scope the "engaged option" concept to what already exists in state, not a new field.**
Rather than block on US-220 or invent a placeholder "elected_option" concept, the prompt instructs
the LLM to reference *whichever* property is already conversationally salient (the property just
shown in the Top-3, or one the lead named). This keeps the change genuinely prompt-only per the
proposal's own alignment note (b), and avoids a false dependency on unmerged work. When US-220 lands
later, it can supply a more precise signal to the same prompt section without requiring another
rewrite of this language.

**Decision 2 — Narrow the human-handoff sentence instead of deleting it.**
The "un asesor humano continuará" sentence still has legitimate uses (explicit "quiero hablar con
una persona", or requests genuinely outside scope). Rather than removing the sentence (which would
regress that real handoff need), it is narrowed to those cases and decoupled from bare
scheduling-intent, which now gets the conversational-invitation treatment instead.

**Decision 3 — Touch three copy surfaces, not one.**
The Gherkin's "the assistant drafts the visit invitation" spans two moments in the real flow: (a)
the Top-3 is first delivered (narrator/composer, LLM-narrated or deterministic fallback) and (b) any
later free-flowing turn in RECOMMENDATION where the lead engages further (`DEFAULT_SYSTEM_PROMPT`
step 4, LLM-driven). Both needed the same reframe for consistency; fixing only one would leave a
visible tonal seam between the initial Top-3 message and the follow-up conversation.

## Risks / Trade-offs

- [Risk] Loosening "quiere agendar -> asesor humano" could be read as encouraging the LLM to promise
  a booking outright → Mitigation: the new instruction explicitly limits the LLM to *suggesting* a
  visit and asking for a day/time preference; it never claims a slot is confirmed — that remains
  `run_scheduling_turn`'s exclusive responsibility, called before the LLM's own reply is ever
  computed for any turn where a date+time is present (coordinator.py's `_scheduling_turn` runs and
  short-circuits ahead of the LLM call).
- [Risk] Test-pinned substrings in `tests/test_prompts.py` could be broken by a broad prompt rewrite
  → Mitigation: only step 4's specific sentence(s) about scheduling/handoff change; every other
  section (steps 1-3, tone, cadence, strict rules) is left untouched, and every existing pinned
  substring is re-verified against the new text before implementation is considered done.

## Migration Plan

No migration — this is a content-only change to in-repo prompt strings, deployed with the next
release like any other code change. No rollback plan beyond a normal revert, since there is no
persisted state to migrate.

## Open Questions

None — the scope decision above (Decision 1) resolves the only ambiguity flagged in the ticket
(dependency on US-220).
