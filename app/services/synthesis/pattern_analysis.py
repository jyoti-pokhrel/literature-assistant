from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from typing import Dict, List

NEPAL_TZ = timezone(timedelta(hours=5, minutes=45))

from app.schemas.synthesis import PatternAnalysis


def _collect_terms(papers: list[dict], key: str) -> list[str]:
    result: list[str] = []
    for paper in papers:
        val = paper.get(key)
        if isinstance(val, list):
            result.extend(v for v in val if v)
        elif isinstance(val, str) and val:
            result.append(val)
    return result


def _top_terms(values: list[str], limit: int = 8) -> list[str]:
    counter = Counter(values)
    return [item for item, _ in counter.most_common(limit)]


def _method_trend_by_year(papers: list[dict]) -> Dict[str, List[str]]:
    trend: dict[str, list[str]] = defaultdict(list)
    for paper in papers:
        year = paper.get("year")
        method = paper.get("normalized_method") or paper.get("method")
        if year and method:
            trend[str(year)].append(method)
    return {y: methods for y, methods in sorted(trend.items())}


def _dataset_frequency(papers: list[dict]) -> Dict[str, int]:
    counter: Counter[str] = Counter()
    for paper in papers:
        for ds in paper.get("normalized_datasets", []):
            if ds:
                counter[ds] += 1
    return dict(counter.most_common(10))


def _metric_frequency(papers: list[dict]) -> Dict[str, int]:
    counter: Counter[str] = Counter()
    for paper in papers:
        for m in paper.get("normalized_metrics", []):
            if m:
                counter[m] += 1
    return dict(counter.most_common(10))


def _baseline_stagnation(papers: list[dict]) -> bool:
    baseline_sets: list[set[str]] = []
    for paper in papers:
        bs = set(paper.get("normalized_baselines", []))
        if bs:
            baseline_sets.append(bs)
    if len(baseline_sets) < 2:
        return False
    ref = baseline_sets[0]
    return all(len(bs & ref) / max(len(ref | bs), 1) >= 0.7 for bs in baseline_sets[1:])


def _emerging_opportunities(
    papers: list[dict],
    current_year: int,
) -> List[str]:
    recent = [p for p in papers if (p.get("year") or 0) >= current_year - 2]
    if not recent:
        return []
    limitation_tokens = _collect_terms(recent, "normalized_limitations")
    future_tokens = _collect_terms(recent, "normalized_future_work")
    combined = limitation_tokens + future_tokens
    top = _top_terms(combined, limit=4)
    return [t.capitalize() for t in top if t]


def _shorten_theme(text: str, max_words: int = 4) -> str:
    """Extract a short 2-4 word label from a limitation/future-work phrase."""
    import re
    # Strip leading filler words common in academic text
    filler = re.compile(
        r'^(in addition|furthermore|however|additionally|moreover|we|our|this|the|'
        r'after|although|since|as a result|due to|based on|given that|'
        r'it is|there is|there are|which|that)\b[,\s]*',
        re.IGNORECASE,
    )
    cleaned = filler.sub('', text).strip(' .,;:')
    # Take the first max_words words
    words = cleaned.split()
    short = ' '.join(words[:max_words])
    return short.capitalize() if short else text[:40].capitalize()


def extract_cluster_themes(cluster_papers: list[dict]) -> dict:

    lim_counter: Counter[str] = Counter()
    fw_counter: Counter[str] = Counter()

    for paper in cluster_papers:
        for lim in paper.get("normalized_limitations") or []:
            if lim and lim.strip():
                lim_counter[lim.strip()] += 1
        for fw in paper.get("normalized_future_work") or []:
            if fw and fw.strip():
                fw_counter[fw.strip()] += 1

    top_lims = [item for item, _ in lim_counter.most_common(5)]
    top_fw = [item for item, _ in fw_counter.most_common(5)]

    # Theme label
    if top_lims:
        raw_label = top_lims[0]
    elif top_fw:
        raw_label = top_fw[0]
    elif cluster_papers:
        # Fallback to common words in titles
        title_words = [w.lower() for p in cluster_papers for w in (p.get("title") or "").split() if len(w) > 3]
        common_titles = Counter(title_words).most_common(2)
        if common_titles:
            raw_label = f"Study of {' '.join(w for w, _ in common_titles)}"
        else:
            raw_label = cluster_papers[0].get("title", "unspecified gap")
    else:
        raw_label = "unspecified gap"

    theme_label = _shorten_theme(raw_label)

    return {
        "top_limitations": top_lims,
        "top_future_work": top_fw,
        "theme_label": theme_label,
        "paper_count": len(cluster_papers),
        "limitation_freq": dict(lim_counter.most_common(10)),
    }


def run_pattern_analysis(papers: list[dict]) -> PatternAnalysis:

    current_year = datetime.now(NEPAL_TZ).year

    methods = _collect_terms(papers, "normalized_method")
    datasets = _collect_terms(papers, "normalized_datasets")
    metrics = _collect_terms(papers, "normalized_metrics")
    limitations = _collect_terms(papers, "normalized_limitations")
    future_work = _collect_terms(papers, "normalized_future_work")

    return PatternAnalysis(
        top_methods=_top_terms(methods),
        top_datasets=_top_terms(datasets),
        top_metrics=_top_terms(metrics),
        top_limitations=_top_terms(limitations),
        top_future_work=_top_terms(future_work),
        method_trend_by_year=_method_trend_by_year(papers),
        dataset_frequency=_dataset_frequency(papers),
        metric_frequency=_metric_frequency(papers),
        baseline_stagnation=_baseline_stagnation(papers),
        emerging_opportunities=_emerging_opportunities(papers, current_year),
    )
