"""DecisionTraceRecorder surfaces the current LangSmith run URL, if a trace
is active, so AIDecisionTrace rows can link out to the full LangSmith trace."""

from unittest.mock import patch

import pytest
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
async def test_trace_decision_persists_langsmith_run_url_when_trace_active(session_factory):
    org_id = new_id()
    fake_run_tree = type("FakeRunTree", (), {"id": "22222222-2222-2222-2222-222222222222"})()

    async with session_factory() as session:
        session.add(OrganizationORM(id=org_id, name="Org", status="active", created_at=utcnow()))
        await session.commit()

    with patch(
        "app.shared.infrastructure.observability.get_current_run_tree",
        return_value=fake_run_tree,
    ):
        async with session_factory() as session:
            async with trace_decision(session, organization_id=org_id, agent_name="test_agent"):
                pass
            await session.commit()

    async with session_factory() as session:
        trace = (await session.execute(select(AIDecisionTraceORM))).scalar_one()
        assert trace.langsmith_run_url == (
            "https://smith.langchain.com/o/-/projects/p/-/r/22222222-2222-2222-2222-222222222222"
        )
