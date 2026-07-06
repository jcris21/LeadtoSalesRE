"""Sprint 0 scope of the Intelligence & AI Admin bounded context: the minimal
versioned Prompt Registry and the AIDecisionTrace record. The full admin UI
(Tool Registry, Guardrails, dashboards) is E12/E13, delivered in Sprint 6/8.

PromptVersion is insert-only: activating a new version never mutates or deletes
a prior one, so `get_active_prompt` is always reproducible for any past trace
(AIDecisionTrace.prompt_version_id).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.shared.domain.base import new_id, utcnow


@dataclass
class PromptVersion:
    id: uuid.UUID
    prompt_template_id: uuid.UUID
    version: str
    content: str
    active: bool
    created_at: object = field(default_factory=utcnow)


@dataclass
class PromptTemplate:
    id: uuid.UUID
    organization_id: uuid.UUID
    agent_name: str

    @classmethod
    def create(cls, organization_id: uuid.UUID, agent_name: str) -> PromptTemplate:
        return cls(id=new_id(), organization_id=organization_id, agent_name=agent_name)


@dataclass
class AIDecisionTrace:
    """One record per AI decision (QA-07): agent, prompt version, tool calls,
    context references, cost, latency, output. Foundation for E13 dashboards."""

    id: uuid.UUID
    organization_id: uuid.UUID
    agent_name: str
    prompt_version_id: uuid.UUID | None
    tool_calls: list[dict]
    context_refs: list[str]
    cost_usd: float | None
    latency_ms: int
    output: dict
    conversation_id: uuid.UUID | None = None
    created_at: object = field(default_factory=utcnow)
