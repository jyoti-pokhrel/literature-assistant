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
