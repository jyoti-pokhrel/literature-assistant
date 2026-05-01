from app.models.paper import Paper
from app.schemas.gap_analysis import GapAnalysisResponse
from app.schemas.paper import RetrievedPaper
from app.services.analysis.gap_detector import analyze_gaps
from app.services.retrieval.fetcher import retrieve_papers


def _split_sentences(text: str | None) -> list[str]:
    if not text:
        return []
    parts = [segment.strip(" .") for segment in text.replace("\n", " ").split(".")]
    return [part for part in parts if len(part) > 10]


def _extract_limitations(text: str | None) -> list[str]:
    results: list[str] = []
    # Keywords that suggest a limitation or a challenge
    limitation_keywords = ["limit", "challenge", "bottleneck", "robustness", "trade-off", "downside", "drawback", "lack of", "underexplored"]
    
    for sentence in _split_sentences(text):
        lowered = sentence.lower()
        # Avoid general descriptions like "this paper explores limitations"
        if any(intro in lowered for intro in ["this paper", "in this work", "we propose", "we present"]):
            continue
            
        if any(token in lowered for token in limitation_keywords):
            results.append(sentence)

    joined = (text or "").lower()
    heuristic_phrases = {
        "baseline comparison is limited": ["baseline", "compare"],
        "evaluation mostly focuses on reward": ["reward"],
        "robustness under noise or partial observability is underexplored": ["partial observability", "noise", "robust"],
        "scaling to more agents remains underexplored": ["scal", "more agents", "large teams"],
    }
    for phrase, triggers in heuristic_phrases.items():
        if any(trigger in joined for trigger in triggers):
            results.append(phrase)
    return list(dict.fromkeys(results))


def _extract_future_work(text: str | None) -> list[str]:
    results: list[str] = []
    # Keywords that specifically suggest future directions
    future_keywords = ["future work", "future direction", "next steps", "avenue for research", "remains for future", "beyond the scope"]
    
    for sentence in _split_sentences(text):
        lowered = sentence.lower()
        # Avoid sentences that are just about what the paper already does
        if any(intro in lowered for intro in ["this paper", "in this work", "we explore", "we evaluate", "we test"]):
            continue
            
        if any(token in lowered for token in future_keywords):
            results.append(sentence)
    return results


def _extract_assumptions(text: str | None) -> list[str]:
    results: list[str] = []
    for sentence in _split_sentences(text):
        lowered = sentence.lower()
        if "full observability" in lowered or "fully observable" in lowered:
            results.append("Full observability")
        if "partial observability" in lowered:
            results.append("Partial observability")
        if "stationary" in lowered:
            results.append("Stationary environment")
        if "fixed number of agents" in lowered:
            results.append("Fixed number of agents")
    return list(dict.fromkeys(results))


def _extract_metrics(text: str | None) -> list[str]:
    text = (text or "").lower()
    metrics: list[str] = []
    if "reward" in text or "return" in text:
        metrics.append("reward")
    if "robust" in text:
        metrics.append("robustness")
    if "transfer" in text or "generalization" in text:
        metrics.append("transfer")
    if "sample efficiency" in text or "data efficiency" in text:
        metrics.append("sample efficiency")
    if "safety" in text:
        metrics.append("safety")
    return list(dict.fromkeys(metrics))


def _extract_datasets(text: str | None) -> list[str]:
    text = text or ""
    known = ["SMAC", "MPE", "Hanabi", "Overcooked", "GRF"]
    return [dataset for dataset in known if dataset.lower() in text.lower()]


def _extract_method(title: str, abstract: str | None) -> str | None:
    text = f"{title}. {abstract or ''}".lower()
    for method in ["transformer", "diffusion", "graph neural network", "policy gradient", "value decomposition", "q learning"]:
        if method in text:
            return method.title()
    return None


def paper_from_retrieved(item: RetrievedPaper) -> dict:
    text = item.abstract or item.title or ""
    paper = Paper(
        paper_id=item.external_id or item.url or item.title,
        title=item.title,
        year=item.year or 0,
        url=item.url,
        abstract=item.abstract,
        method=_extract_method(item.title, item.abstract),
        assumptions=_extract_assumptions(text),
        datasets=_extract_datasets(text),
        metrics=_extract_metrics(text),
        baselines=[],
        limitations=_extract_limitations(text),
        future_work=_extract_future_work(text),
    )
    return {
        "paper": paper,
        "source": item.source,
        "venue": item.venue,
        "citation_count": item.citation_count,
        "url": item.url,
    }


def build_analysis_papers(papers: list[RetrievedPaper]) -> list[dict]:
    return [paper_from_retrieved(item) for item in papers]


async def run_gap_analysis(
    *,
    topic: str,
    year: str | None = None,
    venue: str | None = None,
    max_results: int = 10,
    top_k_gaps: int = 5,
) -> GapAnalysisResponse:
    retrieval = await retrieve_papers(
        topic,
        year=year,
        venue=venue,
        max_results=max_results,
    )
    analysis_papers = build_analysis_papers(retrieval.papers)
    return analyze_gaps(
        topic=retrieval.topic,
        papers=analysis_papers,
        filters=retrieval.filters,
        sources_used=retrieval.sources_used,
        top_k=top_k_gaps,
    )
