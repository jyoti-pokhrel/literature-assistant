import math

import numpy as np
import pytest

from app.services.recommendations.ranker import rank_in_memory


def _unit(v):
    arr = np.array(v, dtype=np.float32)
    return (arr / np.linalg.norm(arr)).tolist()


def _paper(pid: str, embedding, year=2024, citations=10, **rest):
    return {
        "source": "arxiv",
        "external_id": pid,
        "title": pid,
        "embedding": embedding,
        "year": year,
        "citation_count": citations,
        **rest,
    }


@pytest.mark.asyncio
async def test_rank_in_memory_orders_by_similarity():
    query = _unit([1, 0, 0])
    candidates = [
        _paper("near", _unit([0.95, 0.05, 0])),
        _paper("far", _unit([0, 1, 0])),
        _paper("mid", _unit([0.7, 0.7, 0])),
    ]
    ranked = await rank_in_memory(
        query_vectors=[query],
        weights=[1.0],
        candidates=candidates,
        seen_ids=set(),
        page_size=3,
    )
    ids = [p["external_id"] for p in ranked]
    assert ids == ["near", "mid", "far"]


@pytest.mark.asyncio
async def test_rank_in_memory_filters_seen():
    query = _unit([1, 0, 0])
    candidates = [
        _paper("a", _unit([0.9, 0, 0])),
        _paper("b", _unit([0.8, 0, 0])),
    ]
    ranked = await rank_in_memory(
        query_vectors=[query],
        weights=[1.0],
        candidates=candidates,
        seen_ids={"a"},
        page_size=5,
    )
    assert [p["external_id"] for p in ranked] == ["b"]


@pytest.mark.asyncio
async def test_rank_in_memory_skips_missing_embeddings():
    query = _unit([1, 0, 0])
    candidates = [
        _paper("with_emb", _unit([0.9, 0, 0])),
        {"source": "arxiv", "external_id": "no_emb", "title": "x"},  # no embedding
    ]
    ranked = await rank_in_memory(
        query_vectors=[query],
        weights=[1.0],
        candidates=candidates,
        seen_ids=set(),
        page_size=5,
    )
    assert [p["external_id"] for p in ranked] == ["with_emb"]
