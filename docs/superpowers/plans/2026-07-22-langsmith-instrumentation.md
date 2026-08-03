# LangSmith Instrumentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the three raw-httpx Gemini call sites (conversation brain, generative extractor, recommendation narrator) and the LangGraph conversational turn first-class, PII-redacted LangSmith tracing — config-driven and off by default, so no behavior, latency, or test regresses when it is unconfigured.

**Architecture:** LangSmith's `@traceable` decorator (from the `langsmith` SDK) is applied directly to each Gemini adapter's network-calling method (`run_type="llm"`) and to `LangGraphResponder.respond()` (`run_type="chain"`, the root span for one conversational turn). `@traceable` uses contextvars, not LangChain callbacks, so the LLM spans nest correctly under the chain span across the `await self._graph.ainvoke(...)` call without any LangChain `Runnable`/chat-model wrapping and without touching the graph's node structure. Tracing activates only when `LANGSMITH_TRACING=true` is present in the environment; `configure_langsmith_tracing()` sets that (and `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` / `LANGSMITH_ENDPOINT`) from `Settings` once at process boot, mirroring the existing `setup_observability()` OTel wiring in `app/shared/infrastructure/observability.py`. Every payload that reaches LangSmith (system prompts, lead messages, model replies) is passed through a shared `redact_pii()` scrubber first via `@traceable`'s `process_inputs`/`process_outputs` hooks, because lead conversations carry real names, phone numbers and emails and LangSmith is an external SaaS.

**Tech Stack:** `langsmith` Python SDK (`traceable`, `run_helpers.get_current_run_tree`), existing `langgraph`, `httpx`, `pydantic-settings`, `pytest` + `pytest-asyncio` (`asyncio_mode = "auto"`, see `pyproject.toml:49`).

## Global Constraints

- English-only code, comments, commit messages (`docs/base-standards.md:32`).
- TDD: failing test before implementation, for every new function (`docs/base-standards.md:31`).
- `uv` exclusively for dependency and test commands (`docs/base-standards.md:33,62-66`) — every command below uses `uv run ...` / `uv add ...`. **This environment additionally requires the `UV_NATIVE_TLS=true` env var on every `uv` invocation** (local AV TLS interception breaks uv's bundled cert store; native-tls falls back to the Windows system store).
- Secrets via environment variables only, never hardcoded (`docs/base-standards.md:93-94`) — `LANGSMITH_API_KEY` follows `gemini_api_key`'s pattern in `app/core/config.py`: a `Settings` field, never a literal.
- Modules never import each other directly, only via the Event Bus/Outbox (`docs/base-standards.md:26,51`) — the new `redact_pii()` helper lives in `app/shared/infrastructure/`, which every module already depends on (same tier as `observability.py`), so this does not violate module isolation.
- 90%+ coverage requirement (`docs/base-standards.md:34,87`) — every new function gets a directly-targeting unit test in this plan.
- Tracing must be **fail-safe when unconfigured**: with `langsmith_tracing_enabled=False` (the default), zero behavior change, zero new outbound calls, zero import-time side effects — same convention as `gemini_api_key` being optional (`app/core/config.py:65-70`).

---

### Task 1: `Settings` fields, dependency, and `.env.example`

**Files:**
- Modify: `pyproject.toml:22` (dependencies list)
- Modify: `app/core/config.py:81-90` (add fields after the `otel_*` block)
- Modify: `.env.example:28-29` (add after the `OTEL_*` lines)
- Test: `tests/test_langsmith_config.py` (new)

**Interfaces:**
- Produces: `Settings.langsmith_tracing_enabled: bool`, `Settings.langsmith_api_key: str | None`, `Settings.langsmith_project: str`, `Settings.langsmith_endpoint: str | None`, `Settings.langsmith_redact_pii: bool` — consumed by Task 3's `configure_langsmith_tracing()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_langsmith_config.py
"""LangSmith instrumentation config: off by default, same pattern as the
other optional-credential settings (gemini_api_key, otel_exporter_otlp_endpoint)."""

from app.core.config import Settings


def test_langsmith_settings_default_to_disabled_and_redacting(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    settings = Settings(_env_file=None)

    assert settings.langsmith_tracing_enabled is False
    assert settings.langsmith_api_key is None
    assert settings.langsmith_project == "lead-to-sales-system"
    assert settings.langsmith_endpoint is None
    assert settings.langsmith_redact_pii is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_NATIVE_TLS=true uv run pytest tests/test_langsmith_config.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'langsmith_tracing_enabled'`

- [ ] **Step 3: Add the dependency**

Edit `pyproject.toml`, in the `dependencies` list right after `"langgraph-checkpoint-postgres>=3.1.0",` (line 24):

```toml
    "langgraph-checkpoint-postgres>=3.1.0",
    "langsmith>=0.3",
```

Run: `UV_NATIVE_TLS=true uv sync`

- [ ] **Step 4: Add the settings fields**

Edit `app/core/config.py`, insert after the `otel_exporter_otlp_endpoint` line (line 82) and before the `# G13` comment block (line 84):

```python
    otel_service_name: str = "lead-to-sales-system"
    otel_exporter_otlp_endpoint: str | None = None

    # LangSmith instrumentation: traces the conversational turn (LangGraph
    # chain) plus each Gemini call (LLM spans) for latency/quality debugging.
    # Off by default — same optional-credential convention as gemini_api_key:
    # with no key, no outbound calls, no behavior change. `langsmith_redact_pii`
    # gates whether prompts/replies (which carry lead names, phones, emails)
    # are scrubbed before leaving the process; keep this true unless the
    # LangSmith project is self-hosted and inside the same trust boundary.
    langsmith_tracing_enabled: bool = False
    langsmith_api_key: str | None = None
    langsmith_project: str = "lead-to-sales-system"
    langsmith_endpoint: str | None = None
    langsmith_redact_pii: bool = True
```

- [ ] **Step 5: Add `.env.example` entries**

Edit `.env.example`, append after the `OTEL_EXPORTER_OTLP_ENDPOINT=` line (line 29):

```
LANGSMITH_TRACING_ENABLED=false
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=lead-to-sales-system
LANGSMITH_ENDPOINT=
LANGSMITH_REDACT_PII=true
```

- [ ] **Step 6: Run test to verify it passes**

Run: `UV_NATIVE_TLS=true uv run pytest tests/test_langsmith_config.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock app/core/config.py .env.example tests/test_langsmith_config.py
git commit -m "feat: add LangSmith settings, dependency, and env template"
```

---

### Task 2: `redact_pii()` shared scrubber

**Files:**
- Create: `app/shared/infrastructure/pii_redaction.py`
- Test: `tests/test_pii_redaction.py` (new)

**Interfaces:**
- Produces: `redact_pii(text: str) -> str` — consumed by Task 4, 6, 7's `process_inputs`/`process_outputs` hooks.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pii_redaction.py
"""Pure-function PII scrubber for anything sent to the external LangSmith
SaaS: lead conversations carry real emails and phone numbers."""

from app.shared.infrastructure.pii_redaction import redact_pii


def test_redacts_email_addresses():
    text = "Contáctame a maria.lopez@example.com por favor"
    result = redact_pii(text)
    assert "maria.lopez@example.com" not in result
    assert "[REDACTED_EMAIL]" in result


def test_redacts_peru_and_generic_phone_numbers():
    assert "[REDACTED_PHONE]" in redact_pii("Mi número es +51 987 654 321")
    assert "[REDACTED_PHONE]" in redact_pii("Llámame al 987654321")
    assert "[REDACTED_PHONE]" in redact_pii("tel: (01) 555-1234")


def test_leaves_non_pii_text_untouched():
    text = "Busco un departamento de 3 dormitorios en Miraflores, presupuesto 250000 soles"
    assert redact_pii(text) == text


def test_handles_none_and_empty_gracefully():
    assert redact_pii("") == ""
    assert redact_pii(None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_NATIVE_TLS=true uv run pytest tests/test_pii_redaction.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.shared.infrastructure.pii_redaction'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/shared/infrastructure/pii_redaction.py
"""Scrubs PII from text before it leaves the process toward the external
LangSmith SaaS (traces of conversation brain / extractor / narrator calls
carry real lead names, phone numbers and emails). Regex-based and
deliberately conservative — false positives (over-redacting) are safe for a
debugging trace; false negatives are the risk this exists to avoid."""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# Matches +51 987 654 321 / 987654321 / (01) 555-1234 / 555-1234 style runs of
# 6+ digits with optional separators and an optional leading country code —
# generic enough for Peru (+51 9XXXXXXXX) and common landline formats without
# also matching short numbers like bedroom counts or budgets.
_PHONE_RE = re.compile(r"(?:\+?\d{1,3}[\s.-]?)?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}")


def redact_pii(text: str | None) -> str | None:
    if not text:
        return text
    redacted = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    redacted = _PHONE_RE.sub("[REDACTED_PHONE]", redacted)
    return redacted
```

- [ ] **Step 4: Run test to verify it passes**

Run: `UV_NATIVE_TLS=true uv run pytest tests/test_pii_redaction.py -v`
Expected: PASS. If `test_leaves_non_pii_text_untouched` fails because "3 dormitorios" or "250000" gets matched by `_PHONE_RE`, tighten the regex to require at least one separator character or a leading `+`/`(` — re-run until all four tests pass without false-positiving on the budget/bedroom-count sentence.

- [ ] **Step 5: Commit**

```bash
git add app/shared/infrastructure/pii_redaction.py tests/test_pii_redaction.py
git commit -m "feat: add shared PII redaction helper for external trace payloads"
```

---

### Task 3: `configure_langsmith_tracing()` boot wiring

**Files:**
- Modify: `app/shared/infrastructure/observability.py` (add function after `setup_observability`, line 41)
- Modify: `app/main.py:107` (call it next to `setup_observability(app)`)
- Test: `tests/test_langsmith_tracing_config.py` (new)

**Interfaces:**
- Consumes: `Settings.langsmith_*` (Task 1).
- Produces: `configure_langsmith_tracing() -> None` — sets/clears `os.environ["LANGSMITH_TRACING"]`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT`, read by the `langsmith` SDK at call time inside every `@traceable`-decorated function added in Tasks 4/6/7.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_langsmith_tracing_config.py
"""Boot-time env wiring for LangSmith tracing — mirrors setup_observability's
role for OTel. Disabled by default: must not touch os.environ at all."""

import os

from app.core.config import Settings
from app.shared.infrastructure.observability import configure_langsmith_tracing


def _clear_langsmith_env(monkeypatch):
    for var in ("LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_ENDPOINT"):
        monkeypatch.delenv(var, raising=False)


def test_disabled_by_default_leaves_environment_untouched(monkeypatch):
    _clear_langsmith_env(monkeypatch)
    settings = Settings(
        _env_file=None,
        database_url="postgresql://user:pass@localhost/db",
        jwt_secret="test-secret",
    )

    configure_langsmith_tracing(settings)

    assert "LANGSMITH_TRACING" not in os.environ
    assert "LANGSMITH_API_KEY" not in os.environ


def test_enabled_sets_expected_environment_variables(monkeypatch):
    _clear_langsmith_env(monkeypatch)
    settings = Settings(
        _env_file=None,
        database_url="postgresql://user:pass@localhost/db",
        jwt_secret="test-secret",
        langsmith_tracing_enabled=True,
        langsmith_api_key="ls-test-key",
        langsmith_project="my-project",
        langsmith_endpoint="https://eu.api.smith.langchain.com",
    )

    configure_langsmith_tracing(settings)

    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGSMITH_API_KEY"] == "ls-test-key"
    assert os.environ["LANGSMITH_PROJECT"] == "my-project"
    assert os.environ["LANGSMITH_ENDPOINT"] == "https://eu.api.smith.langchain.com"


def test_enabled_without_endpoint_does_not_set_it(monkeypatch):
    _clear_langsmith_env(monkeypatch)
    settings = Settings(
        _env_file=None,
        database_url="postgresql://user:pass@localhost/db",
        jwt_secret="test-secret",
        langsmith_tracing_enabled=True,
        langsmith_api_key="ls-test-key",
    )

    configure_langsmith_tracing(settings)

    assert "LANGSMITH_ENDPOINT" not in os.environ
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_NATIVE_TLS=true uv run pytest tests/test_langsmith_tracing_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'configure_langsmith_tracing'`

- [ ] **Step 3: Write minimal implementation**

Edit `app/shared/infrastructure/observability.py`, add after `setup_observability` (after line 40):

```python
def setup_observability(app: FastAPI) -> None:
    ...
    FastAPIInstrumentor.instrument_app(app)


def configure_langsmith_tracing(settings: "Settings | None" = None) -> None:
    """Activates LangSmith tracing for every `@traceable`-decorated function
    in the process (conversation brain, generative extractor, recommendation
    narrator, LangGraph responder — Tasks 4/6/7) by setting the environment
    variables the `langsmith` SDK reads at call time. A no-op when tracing is
    disabled (the default), so an unconfigured deployment sees zero new
    outbound calls, matching the `gemini_api_key`-unset degrade pattern."""
    settings = settings or get_settings()
    if not settings.langsmith_tracing_enabled:
        return
    os.environ["LANGSMITH_TRACING"] = "true"
    if settings.langsmith_api_key:
        os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    if settings.langsmith_endpoint:
        os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
```

Add `import os` to the top-level imports of `app/shared/infrastructure/observability.py` (after line 8, `import time`) and, for the type hint, import `Settings` under `TYPE_CHECKING`:

```python
from __future__ import annotations

import os
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.intelligence_ai_admin.infrastructure.db_models import AIDecisionTraceORM
from app.shared.domain.base import new_id, utcnow

if TYPE_CHECKING:
    from app.core.config import Settings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `UV_NATIVE_TLS=true uv run pytest tests/test_langsmith_tracing_config.py -v`
Expected: PASS

- [ ] **Step 5: Wire it into app boot**

Edit `app/main.py`, change line 107 from:

```python
setup_observability(app)
```

to:

```python
setup_observability(app)
configure_langsmith_tracing()
```

And update the import on line 58 from:

```python
from app.shared.infrastructure.observability import setup_observability
```

to:

```python
from app.shared.infrastructure.observability import configure_langsmith_tracing, setup_observability
```

- [ ] **Step 6: Run the full existing suite to confirm no regression**

Run: `UV_NATIVE_TLS=true uv run pytest -q`
Expected: PASS (same pass count as before this task — no test imports `app.main` at collection time in a way that would call the real `get_settings()` without `DATABASE_URL`/`JWT_SECRET` set; if this fails on import, check `tests/conftest.py` for how other tests already satisfy `Settings()`'s required fields and mirror that fixture for any test that imports `app.main`).

- [ ] **Step 7: Commit**

```bash
git add app/shared/infrastructure/observability.py app/main.py tests/test_langsmith_tracing_config.py
git commit -m "feat: wire LangSmith tracing activation into app boot"
```

---

### Task 4: Instrument the conversation-brain LLM call

**Files:**
- Modify: `app/modules/conversation_ownership/infrastructure/llm_brain.py:104-145` (`GeminiChatModel.complete`)
- Test: `tests/test_llm_conversation_brain.py` (extend existing file)

**Interfaces:**
- Consumes: `redact_pii()` (Task 2).
- Produces: no new public interface — `GeminiChatModel.complete` keeps its existing `ChatModelPort` signature; only tracing is added.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_llm_conversation_brain.py` (after the last test, `test_gemini_adapter_raises_chat_model_error_on_terminal_http_failure`):

```python
@pytest.mark.asyncio
async def test_gemini_adapter_is_traceable_and_still_returns_reply_when_tracing_disabled():
    """Tracing must be fail-safe: with LANGSMITH_TRACING unset (default test
    environment), decorating complete() with @traceable changes nothing
    observable — same request, same reply, same exception behavior."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response("respuesta trazada")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = GeminiChatModel("test-key", "test-model", client)

    reply = await model.complete(
        system_prompt=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": "hola, mi correo es ana@example.com"}],
    )

    assert reply == "respuesta trazada"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_NATIVE_TLS=true uv run pytest tests/test_llm_conversation_brain.py -v`
Expected: This specific test PASSES already (the method works before decoration) — this is a **characterization test**, not a red/green TDD test; its purpose is to lock current behavior before the decorator is added. Confirm it passes now, then proceed — Step 3 must not break it.

- [ ] **Step 3: Add the `@traceable` decorator**

Edit `app/modules/conversation_ownership/infrastructure/llm_brain.py`. Add imports after line 31 (`import httpx`):

```python
import httpx
from langsmith import traceable

from app.core.config import get_settings
from app.modules.conversation_ownership.application.langgraph_responder import (
    ConversationBrain,
    TemplateBrain,
)
from app.shared.infrastructure.pii_redaction import redact_pii
```

Add two module-level processor functions before `class GeminiChatModel:` (before line 104):

```python
def _redact_complete_inputs(inputs: dict) -> dict:
    return {
        "system_prompt": redact_pii(inputs.get("system_prompt")),
        "messages": [
            {**message, "content": redact_pii(message.get("content"))}
            for message in inputs.get("messages", [])
        ],
    }


def _redact_complete_output(output: object) -> dict:
    return {"reply": redact_pii(output) if isinstance(output, str) else output}
```

Add the decorator directly above `async def complete` (line 116):

```python
    @traceable(
        run_type="llm",
        name="gemini_conversation_brain_complete",
        process_inputs=_redact_complete_inputs,
        process_outputs=_redact_complete_output,
    )
    async def complete(self, *, system_prompt: str, messages: list[dict[str, str]]) -> str:
```

- [ ] **Step 4: Run tests to verify nothing regressed**

Run: `UV_NATIVE_TLS=true uv run pytest tests/test_llm_conversation_brain.py -v`
Expected: PASS — all existing tests plus the new characterization test from Step 1.

- [ ] **Step 5: Commit**

```bash
git add app/modules/conversation_ownership/infrastructure/llm_brain.py tests/test_llm_conversation_brain.py
git commit -m "feat: trace GeminiChatModel.complete with redacted LangSmith LLM span"
```

---

### Task 5: Root chain trace for the conversational turn

**Files:**
- Modify: `app/modules/conversation_ownership/application/langgraph_responder.py:159-164` (`LangGraphResponder.respond`)
- Test: `tests/test_langgraph_responder.py` (extend existing file)

**Interfaces:**
- Consumes: `redact_pii()` (Task 2).
- Produces: no new public interface — `respond()` keeps its existing signature (`system_prompt`, `conversation_id`, `text` -> `str`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_langgraph_responder.py` (after the last test, `test_restart_simulation_new_responder_instance_resumes_shared_checkpoint`):

```python
async def test_respond_is_traceable_and_still_returns_brain_reply_when_tracing_disabled():
    """Characterization test: decorating respond() with @traceable must not
    change its return value or the checkpointed history it produces."""
    responder = LangGraphResponder(brain=RecordingBrain())
    conversation_id = uuid.uuid4()

    reply = await responder.respond(
        system_prompt="prompt", conversation_id=conversation_id, text="hola, soy Ana, 987654321"
    )

    assert reply == "reply-1"
    history = await responder.history(conversation_id)
    assert history[0]["content"] == "hola, soy Ana, 987654321"  # real (unredacted) data persists
```

- [ ] **Step 2: Run test to verify it passes pre-decoration**

Run: `UV_NATIVE_TLS=true uv run pytest tests/test_langgraph_responder.py -v`
Expected: PASS now (characterization test, same rationale as Task 4 Step 2) — confirm before proceeding.

- [ ] **Step 3: Add the `@traceable` decorator with conversation_id metadata**

Edit `app/modules/conversation_ownership/application/langgraph_responder.py`. Add imports after line 40 (`from psycopg_pool import AsyncConnectionPool`):

```python
from psycopg_pool import AsyncConnectionPool
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from app.shared.infrastructure.pii_redaction import redact_pii
```

Add processor functions before `class LangGraphResponder:` (before line 111):

```python
def _redact_respond_inputs(inputs: dict) -> dict:
    return {
        "system_prompt": redact_pii(inputs.get("system_prompt")),
        "text": redact_pii(inputs.get("text")),
        "conversation_id": str(inputs.get("conversation_id")),
    }


def _redact_respond_output(output: object) -> dict:
    return {"reply": redact_pii(output) if isinstance(output, str) else output}
```

Replace `respond` (lines 159-164) with:

```python
    @traceable(
        run_type="chain",
        name="conversation_turn",
        process_inputs=_redact_respond_inputs,
        process_outputs=_redact_respond_output,
    )
    async def respond(self, *, system_prompt: str, conversation_id: uuid.UUID, text: str) -> str:
        run_tree = get_current_run_tree()
        if run_tree is not None:
            run_tree.metadata["conversation_id"] = str(conversation_id)
        result = await self._graph.ainvoke(
            {"system_prompt": system_prompt, "user_input": text},
            config={"configurable": {"thread_id": str(conversation_id)}},
        )
        return result["reply"]
```

- [ ] **Step 4: Run tests to verify nothing regressed**

Run: `UV_NATIVE_TLS=true uv run pytest tests/test_langgraph_responder.py tests/test_langgraph_responder_lifecycle.py tests/test_langgraph_responder_postgres.py tests/test_llm_conversation_brain.py -v`
Expected: PASS — full conversation-ownership suite, including the new characterization test.

- [ ] **Step 5: Commit**

```bash
git add app/modules/conversation_ownership/application/langgraph_responder.py tests/test_langgraph_responder.py
git commit -m "feat: trace the conversational turn as a LangSmith chain root span"
```

---

### Task 6: Instrument the lead-qualification generative extractor

**Files:**
- Modify: `app/modules/lead_qualification/infrastructure/generative_extractor.py:85-130` (`GeminiGenerativeExtractor.extract`)
- Test: existing test file covering `generative_extractor.py` (locate exact filename in Step 1)

**Interfaces:**
- Consumes: `redact_pii()` (Task 2).
- Produces: no new public interface.

- [ ] **Step 1: Locate the existing test file and read `extract`'s full signature**

Run: `UV_NATIVE_TLS=true uv run pytest tests -k "generative" --collect-only -q`

Read the returned file to confirm `extract`'s exact parameter names (research so far only confirmed the method starts at line 98 and posts to `generateContent`; get the literal signature before writing `_redact_extract_inputs`).

- [ ] **Step 2: Write the failing (characterization) test**

Append to the test file found in Step 1, following the same pattern as Task 4/5 Step 1 — call `extract(...)` through a `httpx.MockTransport` fake and assert the return value is unchanged with tracing disabled. Use the exact parameter names read in Step 1 (do not guess).

- [ ] **Step 3: Run test to verify it passes pre-decoration**

Run: `UV_NATIVE_TLS=true uv run pytest <path-from-step-1> -v`
Expected: PASS (characterization test against current behavior).

- [ ] **Step 4: Add the `@traceable` decorator**

Same shape as Task 4 Step 3: import `traceable` from `langsmith` and `redact_pii` from `app.shared.infrastructure.pii_redaction`; add `_redact_extract_inputs` / `_redact_extract_output` module-level functions built from the real signature read in Step 1; decorate `extract` with `@traceable(run_type="llm", name="gemini_generative_extractor_extract", process_inputs=_redact_extract_inputs, process_outputs=_redact_extract_output)`.

- [ ] **Step 5: Run tests to verify nothing regressed**

Run: `UV_NATIVE_TLS=true uv run pytest <path-from-step-1> -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/modules/lead_qualification/infrastructure/generative_extractor.py <test-path-from-step-1>
git commit -m "feat: trace GeminiGenerativeExtractor.extract with redacted LangSmith LLM span"
```

---

### Task 7: Instrument the recommendation narrator

**Files:**
- Modify: `app/modules/recommendation/infrastructure/llm_narrator.py:66-100` (`GeminiRecommendationNarrator.narrate`)
- Test: existing test file covering `llm_narrator.py` (locate exact filename in Step 1)

**Interfaces:**
- Consumes: `redact_pii()` (Task 2).
- Produces: no new public interface.

- [ ] **Step 1: Locate the existing test file and read `narrate`'s full signature**

Run: `UV_NATIVE_TLS=true uv run pytest tests -k "narrator" --collect-only -q`

`narrate(self, *, profile: dict, entries: list[dict]) -> str | None` is already known from the `RecommendationNarrator` protocol at `llm_narrator.py:63`; confirm the same signature on the concrete `GeminiRecommendationNarrator.narrate` (line 76) by reading the file before writing the redaction processor, since `profile`/`entries` may carry lead PII (name, contact info) that a naive `str(inputs)` would leak in full.

- [ ] **Step 2: Write the failing (characterization) test**

Same pattern as Task 6 Step 2, in the located test file: mock the Gemini HTTP call, assert `narrate()`'s return value is unchanged with tracing disabled.

- [ ] **Step 3: Run test to verify it passes pre-decoration**

Run: `UV_NATIVE_TLS=true uv run pytest <path-from-step-1> -v`
Expected: PASS.

- [ ] **Step 4: Add the `@traceable` decorator**

Same shape as Task 4/6: `_redact_narrate_inputs` must recursively redact `profile` (dict of lead fields) and each entry in `entries`, not just top-level string fields — walk every string value in both structures through `redact_pii()`. Decorate `narrate` with `@traceable(run_type="llm", name="gemini_recommendation_narrator_narrate", process_inputs=_redact_narrate_inputs, process_outputs=_redact_narrate_output)`.

- [ ] **Step 5: Run tests to verify nothing regressed**

Run: `UV_NATIVE_TLS=true uv run pytest <path-from-step-1> -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/modules/recommendation/infrastructure/llm_narrator.py <test-path-from-step-1>
git commit -m "feat: trace GeminiRecommendationNarrator.narrate with redacted LangSmith LLM span"
```

---

### Task 8: Correlate the LangSmith run with the existing `AIDecisionTrace` row

**Files:**
- Modify: `app/shared/infrastructure/observability.py:81-101` (`DecisionTraceRecorder`)
- Test: `tests/test_observability.py` (create if it does not already exist — check with `UV_NATIVE_TLS=true uv run pytest tests -k observability --collect-only -q` first)

**Interfaces:**
- Consumes: `langsmith.run_helpers.get_current_run_tree()` (same helper used in Task 5).
- Produces: `DecisionTraceRecorder.langsmith_run_url: str | None` — a new field callers may read; does not change `trace_decision`'s existing call signature.

**Why this task:** `docs/base-standards.md:74` requires "every node must call `AIDecisionTrace.log()` before returning" — the AI Sidebar already reads `AIDecisionTraceORM` rows (`app/shared/infrastructure/observability.py:64-78`). Without this task, LangSmith traces and `AIDecisionTrace` rows are two disconnected records of the same decision; this task adds the LangSmith run's permalink onto the row so a human debugging from the Sidebar can jump straight to the full LangSmith trace.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_observability.py (add if the file does not exist yet)
"""DecisionTraceRecorder surfaces the current LangSmith run URL, if a trace
is active, so AIDecisionTrace rows can link out to the full LangSmith trace."""

from unittest.mock import patch

from app.shared.infrastructure.observability import DecisionTraceRecorder


def test_langsmith_run_url_is_none_when_no_active_trace():
    recorder = DecisionTraceRecorder()
    assert recorder.langsmith_run_url is None


def test_langsmith_run_url_reads_current_run_tree_when_active():
    fake_run_tree = type("FakeRunTree", (), {"id": "11111111-1111-1111-1111-111111111111"})()
    with patch(
        "app.shared.infrastructure.observability.get_current_run_tree",
        return_value=fake_run_tree,
    ):
        recorder = DecisionTraceRecorder()
        assert recorder.langsmith_run_url == (
            "https://smith.langchain.com/o/-/projects/p/-/r/11111111-1111-1111-1111-111111111111"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_NATIVE_TLS=true uv run pytest tests/test_observability.py -v`
Expected: FAIL — `AttributeError: 'DecisionTraceRecorder' object has no attribute 'langsmith_run_url'`

- [ ] **Step 3: Write minimal implementation**

Edit `app/shared/infrastructure/observability.py`: add the import next to the other top-level imports (near the `TYPE_CHECKING` block added in Task 3):

```python
from langsmith.run_helpers import get_current_run_tree
```

Modify `DecisionTraceRecorder` (currently lines 81-101) by adding a property:

```python
class DecisionTraceRecorder:
    """Mutable scratchpad the caller fills in during the `trace_decision` block."""

    def __init__(self) -> None:
        self.tool_calls: list[dict] = []
        self.context_refs: list[str] = []
        self.cost_usd: float | None = None
        self.output: dict = {}

    @property
    def langsmith_run_url(self) -> str | None:
        """Permalink to the active LangSmith run, if `configure_langsmith_tracing()`
        enabled tracing and this call happens inside a traced span (Tasks 4/5/6/7).
        `None` when tracing is disabled or no span is active — callers must treat
        it as optional, same as `cost_usd`."""
        run_tree = get_current_run_tree()
        if run_tree is None:
            return None
        return f"https://smith.langchain.com/o/-/projects/p/-/r/{run_tree.id}"

    def record_tool_call(self, name: str, arguments: dict, result: object) -> None:
        self.tool_calls.append({"name": name, "arguments": arguments, "result": str(result)})

    def record_context_ref(self, ref: str) -> None:
        self.context_refs.append(ref)

    def set_output(self, output: dict) -> None:
        self.output = output

    def set_cost(self, cost_usd: float) -> None:
        self.cost_usd = cost_usd
```

- [ ] **Step 4: Run test to verify it passes**

Run: `UV_NATIVE_TLS=true uv run pytest tests/test_observability.py -v`
Expected: PASS

- [ ] **Step 5: Persist it onto the `AIDecisionTraceORM` row**

Read `app/modules/intelligence_ai_admin/infrastructure/db_models.py`'s `AIDecisionTraceORM` model and, if it has no free-form column for this, add a nullable `langsmith_run_url: Mapped[str | None]` column plus an Alembic migration (follow the existing migration pattern in `alembic/versions/0017_sprint4_2_appointments.py`). Then in `trace_decision` (`app/shared/infrastructure/observability.py:44-78`), add `langsmith_run_url=recorder.langsmith_run_url` to the `AIDecisionTraceORM(...)` constructor call (currently lines 65-77). Write a test in `tests/test_observability.py` asserting the persisted row's `langsmith_run_url` matches `recorder.langsmith_run_url` when a trace is active, following this repo's existing DB-model test pattern (check `tests/` for how `AIDecisionTraceORM` is already exercised, e.g. via an in-memory `aiosqlite` session per `pyproject.toml:35`).

- [ ] **Step 6: Run the full suite**

Run: `UV_NATIVE_TLS=true uv run pytest -q`
Expected: PASS, no regressions across the whole repo.

- [ ] **Step 7: Commit**

```bash
git add app/shared/infrastructure/observability.py app/modules/intelligence_ai_admin/infrastructure/db_models.py alembic/versions/ tests/test_observability.py
git commit -m "feat: link AIDecisionTrace rows to their LangSmith run URL"
```

---

## Rollout note (not a task — operational guidance)

Tracing stays off (`LANGSMITH_TRACING_ENABLED=false`) until a LangSmith project + API key exist. To turn it on in any environment: set `LANGSMITH_TRACING_ENABLED=true` and `LANGSMITH_API_KEY` (and `LANGSMITH_ENDPOINT` only for a non-US-region workspace) in that environment's `.env` / secret store — no code or redeploy needed beyond Task 3 landing. Verify the exact current `langsmith` SDK env var names against the installed version's changelog before flipping this in production (`process_inputs`/`process_outputs` on `@traceable` requires SDK `>=0.1.98`; the `pyproject.toml` floor in Task 1 is `>=0.3`, which satisfies that, but pin/upgrade discipline still applies per this repo's dependency conventions).
