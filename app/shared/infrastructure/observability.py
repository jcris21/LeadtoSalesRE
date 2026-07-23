"""OpenTelemetry wiring + the structured decision-trace helper (QA-07): "every AI
decision emits a structured trace from Sprint 1" — the persistence side (writing
AIDecisionTrace rows) is built here in Sprint 0 so it exists before any agent
lands; the OTel span gives cross-request tracing, the AIDecisionTrace row gives
the queryable record the AI Sidebar and later E13 dashboards read from.
"""

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

_tracer = trace.get_tracer(__name__)


def setup_observability(app: FastAPI) -> None:
    settings = get_settings()
    # OTLP export requires the optional `opentelemetry-exporter-otlp` package; add it
    # and wire the exporter (with BatchSpanProcessor, for production throughput)
    # when a collector is available. SimpleSpanProcessor (synchronous, no
    # background export thread) is intentional here: local/test volume is low
    # and it avoids a daemon thread racing process/interpreter shutdown.
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: settings.otel_service_name}))
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)


def configure_langsmith_tracing(settings: "Settings | None" = None) -> None:
    """Activates LangSmith tracing for every `@traceable`-decorated function
    in the process (conversation brain, generative extractor, recommendation
    narrator, LangGraph responder — Tasks 4/5/6/7) by setting the environment
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


@asynccontextmanager
async def trace_decision(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    agent_name: str,
    prompt_version_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
) -> AsyncIterator[DecisionTraceRecorder]:
    """Wraps one AI decision in an OTel span and persists an AIDecisionTrace row
    on exit, regardless of success (partial traces beat missing traces)."""
    start = time.monotonic()
    recorder = DecisionTraceRecorder()
    with _tracer.start_as_current_span(f"ai_decision.{agent_name}") as span:
        try:
            yield recorder
        finally:
            latency_ms = int((time.monotonic() - start) * 1000)
            span.set_attribute("organization_id", str(organization_id))
            span.set_attribute("agent_name", agent_name)
            span.set_attribute("latency_ms", latency_ms)
            session.add(
                AIDecisionTraceORM(
                    id=new_id(),
                    organization_id=organization_id,
                    agent_name=agent_name,
                    prompt_version_id=prompt_version_id,
                    conversation_id=conversation_id,
                    tool_calls=recorder.tool_calls,
                    context_refs=recorder.context_refs,
                    cost_usd=recorder.cost_usd,
                    latency_ms=latency_ms,
                    output=recorder.output,
                    created_at=utcnow(),
                )
            )


class DecisionTraceRecorder:
    """Mutable scratchpad the caller fills in during the `trace_decision` block."""

    def __init__(self) -> None:
        self.tool_calls: list[dict] = []
        self.context_refs: list[str] = []
        self.cost_usd: float | None = None
        self.output: dict = {}

    def record_tool_call(self, name: str, arguments: dict, result: object) -> None:
        self.tool_calls.append({"name": name, "arguments": arguments, "result": str(result)})

    def record_context_ref(self, ref: str) -> None:
        self.context_refs.append(ref)

    def set_output(self, output: dict) -> None:
        self.output = output

    def set_cost(self, cost_usd: float) -> None:
        self.cost_usd = cost_usd
