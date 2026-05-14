from app.services.recommendations.popular import (
    _popular_score,
    _diversify_by_venue,
)


def test_popular_score_combines_recency_and_citations():
    fresh_hi_cite = _popular_score({"year": 2025, "citation_count": 100})
    fresh_lo_cite = _popular_score({"year": 2025, "citation_count": 0})
    old_hi_cite = _popular_score({"year": 2018, "citation_count": 100})

    # higher citations within the same year beats lower citations
    assert fresh_hi_cite > fresh_lo_cite
    # for the same citations, newer beats older
    assert fresh_hi_cite > old_hi_cite


def test_popular_score_handles_missing_fields():
    assert _popular_score({}) == 0.0
    assert _popular_score({"year": None, "citation_count": None}) == 0.0


def test_diversify_caps_per_venue():
    items = [
        {"external_id": f"a{i}", "venue": "NeurIPS", "_pop_score": 1.0 - i * 0.01}
        for i in range(5)
    ] + [
        {"external_id": f"b{i}", "venue": "ICML", "_pop_score": 0.5 - i * 0.01}
        for i in range(5)
    ]
    out = _diversify_by_venue(items, page_size=4, per_venue_cap=2)
    venues = [p["venue"] for p in out]
    assert venues.count("NeurIPS") <= 2
    assert venues.count("ICML") <= 2
    # top-scoring items still preferred within the cap
    assert out[0]["external_id"] == "a0"


def test_diversify_falls_back_when_one_venue_dominates():
    items = [
        {"external_id": f"a{i}", "venue": "NeurIPS", "_pop_score": 1.0 - i * 0.001}
        for i in range(10)
    ]
    out = _diversify_by_venue(items, page_size=5, per_venue_cap=2)
    # only one venue is available — cap is relaxed so the page fills
    assert len(out) == 5
