import math
from datetime import datetime, timezone, timedelta

NEPAL_TZ = timezone(timedelta(hours=5, minutes=45))

def citation_weight(citation_count: int | None, year: int | None, current_year: int | None = None) -> float:
    current_year = current_year or datetime.now(NEPAL_TZ).year
    citations = max(citation_count or 0, 0)
    age = max((current_year - year), 0) if year else 5
    return math.log1p(citations) / ((1 + age) ** 0.7)


def recency_weight(year: int | None, current_year: int | None = None) -> float:
    current_year = current_year or datetime.now(NEPAL_TZ).year
    if not year:
        return 0.5
    age = max(current_year - year, 0)
    if age <= 2:
        return 1.0
    if age <= 4:
        return 0.8
    if age <= 6:
        return 0.6
    return 0.4


def score_support(candidate_papers: list[dict], current_year: int | None = None) -> float:
    current_year = current_year or datetime.now(NEPAL_TZ).year
    support_count = len(candidate_papers)
    weighted_support = sum(citation_weight(item.get("citation_count"), item.get("year"), current_year) for item in candidate_papers)
    recent_support = sum(1 for item in candidate_papers if recency_weight(item.get("year"), current_year) >= 1.0)
    return round((support_count * 0.5) + (weighted_support * 0.3) + (recent_support * 0.2), 4)


def score_citation_confidence(candidate_papers: list[dict], current_year: int | None = None) -> float:
    current_year = current_year or datetime.now(NEPAL_TZ).year
    if not candidate_papers:
        return 0.0
    influential_support = sum(1 for item in candidate_papers if citation_weight(item.get("citation_count"), item.get("year"), current_year) >= 1.0)
    recent_support = sum(1 for item in candidate_papers if recency_weight(item.get("year"), current_year) >= 1.0)
    return round((len(candidate_papers) * 0.4) + (influential_support * 0.4) + (recent_support * 0.2), 4)


def score_severity(category: str, evidence: dict) -> float:
    text = " ".join(
        evidence.get("recurring_limitations", [])
        + evidence.get("recurring_future_work", [])
        + evidence.get("dominant_assumptions", [])
        + evidence.get("missing_metrics", [])
    ).lower()
    score = 1.0
    high_priority_terms = ["robust", "scal", "deploy", "partial_observability", "safety", "transfer"]
    if any(term in text for term in high_priority_terms):
        score += 1.5
    if category in {"deployment", "evaluation"}:
        score += 0.8
    return round(score, 4)


def score_actionability(category: str, evidence: dict) -> float:
    score = 1.0
    if evidence.get("missing_metrics"):
        score += 1.0
    if evidence.get("missing_datasets"):
        score += 0.8
    if evidence.get("weak_baselines"):
        score += 0.8
    if evidence.get("dominant_assumptions"):
        score += 0.8
    if evidence.get("recurring_future_work"):
        score += 0.6
    if category == "evaluation":
        score += 0.6
    return round(score, 4)


def score_novelty(candidate_papers: list[dict], current_year: int | None = None) -> float:
    current_year = current_year or datetime.now(NEPAL_TZ).year
    if not candidate_papers:
        return 0.0
    recent_ratio = sum(recency_weight(item.get("year"), current_year) for item in candidate_papers) / len(candidate_papers)
    low_direct_citation_ratio = sum(1 for item in candidate_papers if (item.get("citation_count") or 0) < 50) / len(candidate_papers)
    return round((recent_ratio * 1.2) + (low_direct_citation_ratio * 0.8), 4)


def compute_overall_score(
    support_score: float,
    severity_score: float,
    actionability_score: float,
    novelty_score: float,
    citation_confidence_score: float,
) -> float:
    return round(
        (support_score * 0.30)
        + (severity_score * 0.20)
        + (actionability_score * 0.20)
        + (novelty_score * 0.15)
        + (citation_confidence_score * 0.15),
        4,
    )
