"""DecisionTraceRecorder surfaces the current LangSmith run URL, if a trace
is active, so AIDecisionTrace rows can link out to the full LangSmith trace."""

from unittest.mock import patch

import pytest
from langsmith import traceable
from sqlalchemy import select

from app.modules.intelligence_ai_admin.infrastructure.db_models import AIDecisionTraceORM
from app.modules.organization.infrastructure.db_models import OrganizationORM
from app.shared.domain.base import new_id, utcnow
from app.shared.infrastructure.observability import DecisionTraceRecorder, trace_decision


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


@pytest.mark.asyncio
async def test_trace_decision_persists_none_when_tracing_disabled(session_factory):
    """The common case today (LANGSMITH_TRACING unset): the column is
    populated with None, not left unset or erroring."""
    org_id = new_id()

    async with session_factory() as session:
        session.add(OrganizationORM(id=org_id, name="Org", status="active", created_at=utcnow()))
        await session.commit()

    async with session_factory() as session:
        async with trace_decision(session, organization_id=org_id, agent_name="test_agent"):
            pass
        await session.commit()

    async with session_factory() as session:
        trace = (await session.execute(select(AIDecisionTraceORM))).scalar_one()
        assert trace.langsmith_run_url is None


@pytest.mark.asyncio
async def test_trace_decision_root_run_stays_current_through_finally_after_nested_traceable_call(
    session_factory, monkeypatch
):
    """End-to-end proof of the fix: `trace_decision`'s own root LangSmith run
    (established via `langsmith_trace(...)`) stays the "current" run tree
    inside `finally`, even after a nested `@traceable` call inside the block
    (mirroring Tasks 4-7's real call sites, e.g. the LangGraph responder
    called from `coordinator.py`) has executed and torn down its own child
    run context. Without this, `get_current_run_tree()` would read None by
    the time `trace_decision` persists the row, and `langsmith_run_url`
    would never be populated for any real caller — the bug a plain
    `get_current_run_tree`-mock test cannot catch."""
    # `langsmith.utils.get_env_var` is `@functools.lru_cache`d, so toggling
    # LANGSMITH_TRACING via env var mid-process is unreliable once any
    # earlier code (this suite, the pytest-langsmith plugin, etc.) has
    # already called it once. Patching `tracing_is_enabled` directly is the
    # deterministic way to force the "enabled" branch for this one test.
    monkeypatch.setattr("langsmith.utils.tracing_is_enabled", lambda *a, **kw: True)
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_pt_test_fake_key_for_local_context_test_only")
    # Forcing tracing "enabled" makes the SDK submit runs over HTTP on a
    # background thread; with a fake key that attempt fails and logs a
    # warning/traceback (sometimes only visible at interpreter shutdown,
    # since submission is asynchronous). Stubbing `Client.request_with_retries`
    # does NOT reliably suppress this: the background thread can fire the
    # real request after this test function (and its monkeypatch) has
    # already returned, so the patch is gone by the time it's needed —
    # confirmed by testing that approach directly. The noise is cosmetic
    # (does not fail this test or affect the process exit code); avoiding it
    # fully would require patching the SDK's background-thread machinery
    # itself, which is disproportionate to what this test needs to prove.
    org_id = new_id()

    @traceable(run_type="llm", name="nested_call_inside_decision")
    async def nested_llm_call() -> str:
        return "reply"

    async with session_factory() as session:
        session.add(OrganizationORM(id=org_id, name="Org", status="active", created_at=utcnow()))
        await session.commit()

    async with session_factory() as session:
        async with trace_decision(session, organization_id=org_id, agent_name="test_agent"):
            await nested_llm_call()
        await session.commit()

    async with session_factory() as session:
        trace = (await session.execute(select(AIDecisionTraceORM))).scalar_one()
        assert trace.langsmith_run_url is not None
        assert trace.langsmith_run_url.startswith(
            "https://smith.langchain.com/o/-/projects/p/-/r/"
        )
