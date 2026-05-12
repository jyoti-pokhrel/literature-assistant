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
    # Keywords that suggest a limitation or a challenge
    limitation_keywords = [
        "limit", "challenge", "bottleneck", "robust", "trade-off", "downside",
        "drawback", "lack of", "underexplored", "insufficient", "fragile",
        "expensive", "computationally", "hard to", "difficulty", "poor performance",
        "fails to", "cannot handle", "unable to", "stagnation", "complexity"
    ]
    
    for sentence in _split_sentences(text):
        lowered = sentence.lower()
        # Avoid general descriptions like "this paper explores limitations"
        if any(intro in lowered for intro in ["this paper", "in this work", "we propose", "we present", "this work"]):
            continue
            
        if any(token in lowered for token in limitation_keywords):
            results.append(sentence)

    joined = (text or "").lower()
    heuristic_phrases = {
        "baseline comparison is limited": ["baseline", "compare", "limited comparison"],
        "evaluation mostly focuses on reward": ["reward", "focus on reward"],
        "robustness under noise or partial observability is underexplored": ["partial observability", "noise", "robust", "uncertainty"],
        "scaling to more agents remains underexplored": ["scal", "more agents", "large teams", "many agents"],
        "high computational overhead": ["overhead", "compute", "costly"],
        "sample inefficiency": ["sample efficiency", "data hungry"],
    }
    for phrase, triggers in heuristic_phrases.items():
        if any(trigger in joined for trigger in triggers):
            results.append(phrase)
    return list(dict.fromkeys(results))


def _extract_future_work(text: str | None) -> list[str]:
    results: list[str] = []
    # Keywords that specifically suggest future directions
    future_keywords = ["future work", "future direction", "next steps", "avenue for research", "remains for future", "beyond the scope", "future studies", "investigate further"]
    
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
        if "partial observability" in lowered or "partially observable" in lowered:
            results.append("Partial observability")
        if "stationary" in lowered:
            results.append("Stationary environment")
        if "fixed number of agents" in lowered or "fixed agents" in lowered:
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
    if "latency" in text or "delay" in text:
        metrics.append("latency")
    return list(dict.fromkeys(metrics))


def _extract_datasets(text: str | None) -> list[str]:
    import re
    text = text or ""
    # Broaden the known benchmarks and environments
    known = [
        "SMAC", "MPE", "Hanabi", "Overcooked", "GRF", "Mujoco", "PettingZoo",
        "Flatland", "Pommerman", "MAgent", "LuxAI", "Neural MMO", "Melting Pot",
        "MNIST", "CIFAR", "ImageNet", "Kuzushiji", "Fashion-MNIST",
        "Atari", "Gym", "Procgen", "Safety Gym", "DeepMind Lab", "Isaac Gym"
    ]
    results = [dataset for dataset in known if dataset.lower() in text.lower()]
    
    # Regex for potential acronym-style benchmarks (e.g., AD-MARL, QMIX-Bench)
    # Looking for 2+ uppercase letters, possibly with dashes/numbers
    acronyms = re.findall(r'\b[A-Z]{2,}(?:-[A-Z0-9]+)*\b', text)
    non_dataset_acr = {
        "MARL", "RL", "AI", "ML", "PPO", "DQN", "QMIX", "MADDPG", "COMA", 
        "IQL", "VDN", "MAPPO", "IPPO", "CTDE", "MDP", "POMDP", "SGD", "CNN", "RNN", "LSTM",
        "CPU", "GPU", "JAX", "TPU", "CUDA", "RAM", "SOTA"
    }
    for acr in acronyms:
        if acr not in known and acr not in non_dataset_acr and 2 < len(acr) <= 12:
             results.append(acr)
    
    return list(dict.fromkeys(results))


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
    strict_venue: bool = False,
    max_results: int = 10,
    top_k_gaps: int = 5,
) -> GapAnalysisResponse:
    retrieval = await retrieve_papers(
        topic,
        year=year,
        venue=venue,
        strict_venue=strict_venue,
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
