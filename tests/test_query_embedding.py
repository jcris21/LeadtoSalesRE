"""G2 (docs/e2e-manual-chat-checklist.md): the BuyerProfile query embeds in
the same space as the property corpus, and retrieval never crashes on a
dimensionality mismatch — the pgvector SQL path only runs when the query
vector's length matches the stored embeddings."""

import pytest

from app.modules.lead_qualification.domain.models import (
    BuyerProfile,
    MoneyRange,
    PropertyType,
)
from app.modules.recommendation.application.retrieval import SemanticRetrievalService
from app.modules.recommendation.domain.models import Property, PropertyEmbedding
from app.modules.recommendation.infrastructure.embedding_model import (
    _profile_query_text,
    build_profile_query_embedder,
)
from app.shared.domain.base import new_id, utcnow


def _property(external_id: str) -> Property:
    return Property(
        id=new_id(),
        organization_id=new_id(),
        external_id=external_id,
        price=250000.0,
        zone="Miraflores",
        property_type=PropertyType.APARTMENT,
        features=("balcon",),
        description="Departamento con balcon",
        updated_at=utcnow(),
    )


def _profile() -> BuyerProfile:
    return BuyerProfile(
        lead_id=new_id(),
        budget=MoneyRange(minimum=200000.0, maximum=300000.0),
        locations=("Miraflores",),
        property_type=PropertyType.APARTMENT,
        must_haves=("cochera", "balcon"),
    )


class FakeStore:
    """PropertyLookup fake with a controllable embedding table and a SQL path
    that records whether it was reached."""

    def __init__(self, embeddings: dict, sql_result=None):
        self._embeddings = embeddings
        self.sql_result = sql_result
        self.sql_calls: list[tuple[float, ...]] = []

    async def get_embedding(self, property_id):
        return self._embeddings.get(property_id)

    async def semantic_search(self, *, candidate_ids, query_vector, top_n):
        self.sql_calls.append(tuple(query_vector))
        return self.sql_result


def _embedding(property_id, vector) -> PropertyEmbedding:
    return PropertyEmbedding(
        property_id=property_id,
        vector=tuple(vector),
        model_version="test",
        computed_at=utcnow(),
    )


@pytest.mark.asyncio
async def test_async_embed_query_is_awaited_and_sql_path_runs_on_matching_dims():
    candidates = [_property("P-1"), _property("P-2")]
    store = FakeStore(
        embeddings={c.id: _embedding(c.id, (1.0, 0.0, 0.0)) for c in candidates},
        sql_result=[candidates[1]],
    )

    async def embed_query(profile):
        return (1.0, 0.0, 0.0)

    service = SemanticRetrievalService(store, embed_query=embed_query)
    ranked = await service.retrieve(buyer_profile=_profile(), candidates=candidates, top_n=2)

    assert ranked == [candidates[1]]  # SQL path answered
    assert store.sql_calls == [(1.0, 0.0, 0.0)]


@pytest.mark.asyncio
async def test_dimension_mismatch_skips_sql_and_falls_back_in_memory():
    candidates = [_property("P-1"), _property("P-2")]
    # Stored vectors are 5-dim; the default query embedder produces 3-dim.
    store = FakeStore(
        embeddings={c.id: _embedding(c.id, (0.1, 0.2, 0.3, 0.4, 0.5)) for c in candidates},
        sql_result=[candidates[0]],
    )

    service = SemanticRetrievalService(store)  # default 3-dim embed_query
    ranked = await service.retrieve(buyer_profile=_profile(), candidates=candidates, top_n=2)

    assert store.sql_calls == []  # pgvector `<->` never reached => no crash
    assert set(ranked) == set(candidates)  # neutral in-memory scores, same set


@pytest.mark.asyncio
async def test_query_embedding_failure_degrades_to_unranked_candidates():
    candidates = [_property("P-1"), _property("P-2"), _property("P-3")]
    store = FakeStore(embeddings={}, sql_result=[candidates[0]])

    async def broken_embed(profile):
        raise RuntimeError("embeddings API down")

    service = SemanticRetrievalService(store, embed_query=broken_embed)
    ranked = await service.retrieve(buyer_profile=_profile(), candidates=candidates, top_n=2)

    assert ranked == candidates[:2]  # hard-filtered order, capped at top_n
    assert store.sql_calls == []


@pytest.mark.asyncio
async def test_no_stored_embeddings_yields_empty_without_touching_sql():
    candidates = [_property("P-1")]
    store = FakeStore(embeddings={}, sql_result=[candidates[0]])

    service = SemanticRetrievalService(store)
    ranked = await service.retrieve(buyer_profile=_profile(), candidates=candidates, top_n=2)

    assert ranked == []
    assert store.sql_calls == []


def test_profile_query_text_mirrors_property_encoding():
    text = _profile_query_text(_profile())
    assert text == "cochera, balcon | Miraflores | apartment"


def test_build_profile_query_embedder_disabled_without_key():
    assert build_profile_query_embedder(None) is None
    assert build_profile_query_embedder("sk-test") is not None
