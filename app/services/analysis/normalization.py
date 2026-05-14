import re
from collections import Counter
from typing import Iterable

from app.models.paper import Paper


METRIC_ALIASES = {
    "reward": "reward",
    "average reward": "reward",
    "return": "reward",
    "accuracy": "accuracy",
    "acc": "accuracy",
    "sample efficiency": "sample_efficiency",
    "data efficiency": "sample_efficiency",
    "robustness": "robustness",
    "transfer": "transfer",
    "generalization": "transfer",
    "latency": "latency",
    "safety": "safety",
    "fairness": "fairness",
    "interpretability": "interpretability",
    "reproducibility": "reproducibility",
}

ASSUMPTION_ALIASES = {
    "full observability": "full_observability",
    "fully observable setting": "full_observability",
    "partial observability": "partial_observability",
    "stationary environment": "stationary_environment",
    "fixed number of agents": "fixed_agent_count",
}


def normalize_text_token(value: str | None) -> str:
    if not value:
        return ""
    normalized = value.strip().lower()
    normalized = re.sub(r"[^a-z0-9\s_-]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def normalize_phrase_list(values: Iterable[str] | None) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    for value in values or []:
        normalized = normalize_text_token(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        results.append(normalized)
    return results


def canonicalize_metric(metric: str) -> str:
    normalized = normalize_text_token(metric)
    return METRIC_ALIASES.get(normalized, normalized.replace(" ", "_"))


def canonicalize_assumption(assumption: str) -> str:
    normalized = normalize_text_token(assumption)
    return ASSUMPTION_ALIASES.get(normalized, normalized.replace(" ", "_"))


def canonicalize_limitation_or_future_work(text: str) -> str:
    normalized = normalize_text_token(text)
    replacements = {
        "fully observable": "full observability",
        "partial observation": "partial observability",
        "noisy sensor": "sensor noise",
        "sensor dropout": "sensor dropout",
    }
    for old, new in replacements.items():
        normalized = normalized.replace(old, new)
    return normalized


def normalize_analysis_paper(item: dict) -> dict:
    paper: Paper = item["paper"]
    method = normalize_text_token(paper.method)
    domain = normalize_text_token(paper.domain)
    limitations = [
        canonicalize_limitation_or_future_work(v)
        for v in normalize_phrase_list(paper.limitations)
    ]
    future_work = [
        canonicalize_limitation_or_future_work(v)
        for v in normalize_phrase_list(paper.future_work)
    ]
    assumptions = [
        canonicalize_assumption(v) for v in normalize_phrase_list(paper.assumptions)
    ]
    datasets = normalize_phrase_list(paper.datasets)
    metrics = [canonicalize_metric(v) for v in normalize_phrase_list(paper.metrics)]
    baselines = normalize_phrase_list(paper.baselines)

    return {
        **item,
        "paper_id": paper.paper_id,
        "title": paper.title,
        "year": paper.year or None,
        "abstract": paper.abstract,
        "method": paper.method,
        "domain": paper.domain,
        "normalized_method": method,
        "normalized_domain": domain,
        "normalized_limitations": limitations,
        "normalized_future_work": future_work,
        "normalized_assumptions": assumptions,
        "normalized_datasets": datasets,
        "normalized_metrics": metrics,
        "normalized_baselines": baselines,
    }


def top_terms(values: Iterable[str], limit: int = 5) -> list[str]:
    counter = Counter(value for value in values if value)
    return [item for item, _count in counter.most_common(limit)]
