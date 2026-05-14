from datetime import datetime, timezone

from app.services.recommendations import scoring


def test_recency_score_within_window():
    current_year = datetime.now(timezone.utc).year
    assert scoring.recency_score(current_year) == 1.0
    assert scoring.recency_score(2020) == 0.0
    assert 0 < scoring.recency_score(2022) < 1


def test_recency_score_handles_invalid():
    assert scoring.recency_score(None) == 0.0
    assert scoring.recency_score("not-a-year") == 0.0


def test_citation_score_monotonic():
    assert scoring.citation_score(0) == 0.0
    assert scoring.citation_score(10) < scoring.citation_score(1000)
    assert scoring.citation_score(10**8) == 1.0  # clamped


def test_cosine_normalized():
    assert scoring.cosine([1, 0, 0], [1, 0, 0]) == 1.0
    assert scoring.cosine([1, 0, 0], [0, 1, 0]) == 0.0
    assert scoring.cosine([0, 0, 0], [1, 0, 0]) == 0.0  # zero-vector guard


def test_composite_score_weights():
    s = scoring.composite_score(
        vector_score=1.0, recency=1.0, citations=1.0, affinity=0.0
    )
    # 0.65*1 + 0.15*1 + 0.10*1 + 0.10*0 = 0.90
    assert abs(s - 0.90) < 1e-6


def test_composite_score_affinity_adds():
    no_aff = scoring.composite_score(0.5, 0.5, 0.5, affinity=0.0)
    with_aff = scoring.composite_score(0.5, 0.5, 0.5, affinity=1.0)
    assert with_aff > no_aff


def test_interleave_balanced_by_weight():
    a = [{"id": "a1"}, {"id": "a2"}, {"id": "a3"}, {"id": "a4"}]
    b = [{"id": "b1"}, {"id": "b2"}]
    result = scoring.interleave_by_weight(
        lists=[a, b], weights=[2.0, 1.0], limit=6, key=lambda d: d["id"]
    )
    ids = [d["id"] for d in result]
    # heavier list contributes ~2/3, lighter ~1/3 — with limit 6, expect 4 a's, 2 b's
    assert ids.count("a1") + ids.count("a2") + ids.count("a3") + ids.count("a4") == 4
    assert ids.count("b1") + ids.count("b2") == 2
    # no duplicates
    assert len(set(ids)) == 6


def test_interleave_dedups_across_lists():
    a = [{"id": "x"}, {"id": "a2"}]
    b = [{"id": "x"}, {"id": "b2"}]
    result = scoring.interleave_by_weight(
        lists=[a, b], weights=[1.0, 1.0], limit=4, key=lambda d: d["id"]
    )
    ids = [d["id"] for d in result]
    assert ids.count("x") == 1
    assert set(ids) == {"x", "a2", "b2"}


def test_interleave_respects_limit():
    a = [{"id": f"a{i}"} for i in range(10)]
    result = scoring.interleave_by_weight(
        lists=[a], weights=[1.0], limit=3, key=lambda d: d["id"]
    )
    assert len(result) == 3
