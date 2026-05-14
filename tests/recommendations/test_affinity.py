import pytest

from app.services.recommendations.affinity import (
    AffinityProfile,
    affinity_score_for_paper,
)


def test_affinity_score_zero_when_empty():
    prof = AffinityProfile(authors={}, venues={})
    assert affinity_score_for_paper({"authors": ["Alice"], "venue": "NeurIPS"}, prof) == 0.0


def test_affinity_score_author_match():
    prof = AffinityProfile(authors={"alice": 1.0}, venues={})
    s = affinity_score_for_paper({"authors": ["Alice", "Bob"], "venue": "X"}, prof)
    assert 0 < s <= 1.0


def test_affinity_score_venue_match():
    prof = AffinityProfile(authors={}, venues={"neurips": 1.0})
    s = affinity_score_for_paper({"authors": [], "venue": "NeurIPS 2024"}, prof)
    assert 0 < s <= 1.0


def test_affinity_score_clamped():
    prof = AffinityProfile(
        authors={"alice": 10.0, "bob": 10.0},
        venues={"neurips": 10.0},
    )
    s = affinity_score_for_paper(
        {"authors": ["Alice", "Bob"], "venue": "NeurIPS"}, prof
    )
    assert s <= 1.0
