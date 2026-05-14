from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
import re

from app.schemas.gap_analysis import (
    CandidateGap,
    EvidenceSummary,
    GapAnalysisResponse,
    GapEvidence,
    SupportingPaperRef,
)
from app.services.analysis.normalization import normalize_analysis_paper, top_terms
from app.services.analysis.scoring import (
    citation_weight,
    compute_overall_score,
    score_actionability,
    score_citation_confidence,
    score_novelty,
    score_severity,
    score_support,
)


NEPAL_TZ = timezone(timedelta(hours=5, minutes=45))


def _supporting_refs(papers: list[dict]) -> list[SupportingPaperRef]:
    ranked = sorted(
        papers,
        key=lambda item: ((item.get("citation_count") or 0), (item.get("year") or 0)),
        reverse=True,
    )
    return [
        SupportingPaperRef(
            paper_id=item.get("paper_id"),
            title=item.get("title") or item["paper"].title,
            year=item.get("year"),
            citation_count=item.get("citation_count"),
            source=item.get("source"),
            venue=item.get("venue"),
        )
        for item in ranked[:5]
    ]


def _counts(papers: list[dict], current_year: int) -> tuple[int, int, int]:
    support = len(papers)
    recent = sum(
        1 for item in papers if item.get("year") and item["year"] >= current_year - 2
    )
    influential = sum(
        1
        for item in papers
        if citation_weight(item.get("citation_count"), item.get("year"), current_year)
        >= 1.0
    )
    return support, recent, influential


def _category_from_text(text: str, default: str = "methodology") -> str:
    lowered = text.lower()
    if any(
        term in lowered
        for term in [
            "robust",
            "metric",
            "benchmark",
            "baseline",
            "evaluation",
            "reward",
            "transfer",
        ]
    ):
        return "evaluation"
    if any(
        term in lowered
        for term in [
            "deploy",
            "real world",
            "scal",
            "sensor",
            "partial observability",
            "communication",
        ]
    ):
        return "deployment"
    return default


def _slug(text: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text or "gap"


def _humanize_token(value: str) -> str:
    return value.replace("_", " ").strip()


def _format_list(items: list[str], limit: int = 3) -> str:
    cleaned = [_humanize_token(item) for item in items if item]
    if not cleaned:
        return ""
    trimmed = cleaned[:limit]
    if len(trimmed) == 1:
        return trimmed[0]
    if len(trimmed) == 2:
        return f"{trimmed[0]} and {trimmed[1]}"
    return ", ".join(trimmed[:-1]) + f", and {trimmed[-1]}"


def _leading_titles(papers: list[dict], limit: int = 3) -> str:
    titles = [item.title for item in _supporting_refs(papers)[:limit] if item.title]
    return "; ".join(titles)


def _build_gap(
    *,
    text: str,
    category: str,
    papers: list[dict],
    current_year: int,
    recurring_limitations: list[str] | None = None,
    recurring_future_work: list[str] | None = None,
    dominant_assumptions: list[str] | None = None,
    missing_metrics: list[str] | None = None,
    missing_datasets: list[str] | None = None,
    weak_baselines: list[str] | None = None,
    statement: str,
    why_it_matters: str,
    actionable_opportunity: str,
) -> CandidateGap:
    support_count, recent_support_count, influential_support_count = _counts(
        papers, current_year
    )
    evidence_dict = {
        "recurring_limitations": recurring_limitations or [],
        "recurring_future_work": recurring_future_work or [],
        "dominant_assumptions": dominant_assumptions or [],
        "missing_metrics": missing_metrics or [],
        "missing_datasets": missing_datasets or [],
        "weak_baselines": weak_baselines or [],
    }
    support_score = score_support(papers, current_year)
    severity_score = score_severity(category, evidence_dict)
    actionability_score = score_actionability(category, evidence_dict)
    novelty_score = score_novelty(papers, current_year)
    citation_confidence_score = score_citation_confidence(papers, current_year)
    overall_score = compute_overall_score(
        support_score,
        severity_score,
        actionability_score,
        novelty_score,
        citation_confidence_score,
    )
    return CandidateGap(
        gap_id=_slug(text),
        category=category,
        title=text.capitalize(),
        statement=statement,
        why_it_matters=why_it_matters,
        actionable_opportunity=actionable_opportunity,
        evidence=GapEvidence(
            support_count=support_count,
            recent_support_count=recent_support_count,
            influential_support_count=influential_support_count,
            recurring_limitations=recurring_limitations or [],
            recurring_future_work=recurring_future_work or [],
            dominant_assumptions=dominant_assumptions or [],
            missing_metrics=missing_metrics or [],
            missing_datasets=missing_datasets or [],
            weak_baselines=weak_baselines or [],
            supporting_papers=_supporting_refs(papers),
        ),
        support_score=support_score,
        severity_score=severity_score,
        actionability_score=actionability_score,
        novelty_score=novelty_score,
        citation_confidence_score=citation_confidence_score,
        overall_score=overall_score,
    )


def detect_recurring_limitation_gaps(
    papers: list[dict], current_year: int
) -> list[CandidateGap]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for paper in papers:
        for limitation in paper.get("normalized_limitations", []):
            groups[limitation].append(paper)

    gaps: list[CandidateGap] = []
    for limitation, supporting in groups.items():
        if len(supporting) < 2:
            continue
        if limitation in {
            "baseline comparison is limited",
            "evaluation mostly focuses on reward",
        }:
            continue
        category = _category_from_text(limitation)
        gaps.append(
            _build_gap(
                text=limitation,
                category=category,
                papers=supporting,
                current_year=current_year,
                recurring_limitations=[limitation],
                statement=f"A recurring limitation in the literature is {limitation}, appearing across {len(supporting)} papers.",
                why_it_matters="This recurring weakness suggests the current literature still lacks convincing evidence on this failure mode.",
                actionable_opportunity=_actionable_from_text(limitation, category),
            )
        )
    return gaps


def detect_future_work_convergence_gaps(
    papers: list[dict], current_year: int
) -> list[CandidateGap]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for paper in papers:
        for item in paper.get("normalized_future_work", []):
            groups[item].append(paper)

    gaps: list[CandidateGap] = []
    for theme, supporting in groups.items():
        if len(supporting) < 2:
            continue
        category = _category_from_text(theme)
        gaps.append(
            _build_gap(
                text=theme,
                category=category,
                papers=supporting,
                current_year=current_year,
                recurring_future_work=[theme],
                statement=f"Multiple papers identify {theme} as a remaining open direction.",
                why_it_matters="When several authors independently point to the same next step, it signals a persistent unresolved direction rather than an isolated suggestion.",
                actionable_opportunity=_actionable_from_text(theme, category),
            )
        )
    return gaps


def detect_assumption_concentration_gaps(
    papers: list[dict], current_year: int
) -> list[CandidateGap]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for paper in papers:
        for assumption in paper.get("normalized_assumptions", []):
            groups[assumption].append(paper)

    threshold = max(2, int(len(papers) * 0.3 + 0.999))
    gaps: list[CandidateGap] = []
    for assumption, supporting in groups.items():
        if len(supporting) < threshold:
            continue
        category = (
            "deployment"
            if "observability" in assumption or "stationary" in assumption
            else "methodology"
        )
        gaps.append(
            _build_gap(
                text=f"over reliance on {assumption.replace('_', ' ')}",
                category=category,
                papers=supporting,
                current_year=current_year,
                dominant_assumptions=[assumption],
                statement=f"The literature is heavily concentrated around the assumption of {assumption.replace('_', ' ')}, limiting evidence for more realistic settings.",
                why_it_matters="This assumption concentration can make strong results brittle outside idealized conditions.",
                actionable_opportunity=_actionable_from_assumption(assumption),
            )
        )
    return gaps


def detect_evaluation_gaps(papers: list[dict], current_year: int) -> list[CandidateGap]:
    if not papers:
        return []

    metric_counter = Counter(
        metric for paper in papers for metric in paper.get("normalized_metrics", [])
    )
    dataset_counter = Counter(
        dataset for paper in papers for dataset in paper.get("normalized_datasets", [])
    )
    baseline_counter = Counter(
        b for paper in papers for b in paper.get("normalized_baselines", [])
    )
    gaps: list[CandidateGap] = []

    total_metric_mentions = sum(metric_counter.values())
    if total_metric_mentions:
        dominant_metric, dominant_count = metric_counter.most_common(1)[0]
        if dominant_count / total_metric_mentions >= 0.6:
            expected = {"robustness", "transfer", "sample_efficiency", "safety"}
            missing = sorted(item for item in expected if item not in metric_counter)
            if missing:
                gaps.append(
                    _build_gap(
                        text=f"narrow evaluation beyond {dominant_metric.replace('_', ' ')}",
                        category="evaluation",
                        papers=papers,
                        current_year=current_year,
                        missing_metrics=missing,
                        statement=f"Evaluation is dominated by {dominant_metric.replace('_', ' ')} style reporting, with limited evidence on {', '.join(missing)}.",
                        why_it_matters="This makes it difficult to judge whether reported gains survive under realistic robustness, transfer, and efficiency demands.",
                        actionable_opportunity="Add a standardized evaluation protocol that reports robustness, transfer, and efficiency metrics alongside headline performance.",
                    )
                )

    if dataset_counter:
        dominant_dataset, dominant_dataset_count = dataset_counter.most_common(1)[0]
        total_dataset_mentions = sum(dataset_counter.values())
        if dominant_dataset_count / max(total_dataset_mentions, 1) >= 0.7:
            gaps.append(
                _build_gap(
                    text=f"benchmark concentration on {dominant_dataset}",
                    category="evaluation",
                    papers=papers,
                    current_year=current_year,
                    missing_datasets=[dominant_dataset],
                    statement=f"Most studies rely on {dominant_dataset}, limiting evidence for cross benchmark generalization.",
                    why_it_matters="A narrow benchmark base can hide benchmark-specific overfitting and overstate general applicability.",
                    actionable_opportunity="Create a cross-benchmark evaluation protocol to test whether methods generalize beyond the dominant benchmark.",
                )
            )

    if len(baseline_counter) <= 1 and len(papers) >= 3:
        weak = list(baseline_counter.keys()) or ["sparse baselines"]
        missing_strong_baselines = [
            baseline
            for baseline in [
                "independent learners",
                "value decomposition",
                "centralized critic",
                "transformer coordination",
            ]
            if baseline not in baseline_counter
        ]
        baseline_context = _format_list(weak)
        missing_context = _format_list(missing_strong_baselines)
        paper_examples = _leading_titles(papers)
        gaps.append(
            _build_gap(
                text="missing strong baseline comparisons",
                category="evaluation",
                papers=papers,
                current_year=current_year,
                weak_baselines=weak + missing_strong_baselines,
                statement=(
                    f"The retrieved literature does not compare methods against a convincing spread of strong baselines. "
                    f"Most papers only report results against {baseline_context or 'very sparse baselines'}, while alternatives such as {missing_context or 'strong recent baselines'} are usually absent."
                ),
                why_it_matters=(
                    f"That makes it hard to tell whether the gains reflect genuine progress or just wins against weak comparison points. "
                    f"This pattern shows up across papers like {paper_examples}."
                ),
                actionable_opportunity=(
                    "Create an evaluation suite with at least one simple independent learner baseline, one cooperative MARL baseline, "
                    "and one stronger recent coordination model under matched compute, data, and tuning budgets, then report exactly where the proposed method still wins and where it breaks."
                ),
            )
        )

    return gaps


def _actionable_from_assumption(assumption: str) -> str:
    if assumption == "full_observability":
        return "Evaluate leading methods under partial observability, delayed sensing, or missing-state conditions, and report robustness and recovery metrics."
    if assumption == "stationary_environment":
        return "Benchmark methods under non-stationary dynamics and changing agent behavior to test adaptation under drift."
    if assumption == "fixed_agent_count":
        return "Evaluate whether methods still work when the number of agents changes over time and report scaling behavior explicitly."
    return "Relax the dominant simplifying assumption and test whether leading methods remain effective under more realistic conditions."


def _actionable_from_text(text: str, category: str) -> str:
    lowered = text.lower()
    if "robust" in lowered or "sensor" in lowered or "partial observability" in lowered:
        return "Build a robustness benchmark with observability degradation, sensor noise, and communication failure, and compare leading methods on reward, failure rate, and recovery latency."
    if "scal" in lowered:
        return "Run scaling studies over larger agent counts and tighter communication budgets, and report performance-efficiency tradeoffs."
    if "deploy" in lowered or category == "deployment":
        return "Evaluate methods in more realistic deployment settings, including non-ideal sensing, delayed feedback, and operational constraints."
    return "Turn this recurring weakness into a focused benchmark or ablation study and compare against strong baselines under the missing condition."


def merge_overlapping_gaps(candidates: list[CandidateGap]) -> list[CandidateGap]:
    best_by_key: dict[tuple[str, str], CandidateGap] = {}
    for gap in candidates:
        key = (gap.category, _slug(gap.title.replace("over reliance on ", "")))
        existing = best_by_key.get(key)
        if existing is None or gap.overall_score > existing.overall_score:
            best_by_key[key] = gap
    return list(best_by_key.values())


def build_evidence_summary(papers: list[dict]) -> EvidenceSummary:
    return EvidenceSummary(
        top_methods=top_terms(paper.get("normalized_method") for paper in papers),
        top_datasets=top_terms(
            dataset
            for paper in papers
            for dataset in paper.get("normalized_datasets", [])
        ),
        top_metrics=top_terms(
            metric for paper in papers for metric in paper.get("normalized_metrics", [])
        ),
        top_assumptions=top_terms(
            assumption
            for paper in papers
            for assumption in paper.get("normalized_assumptions", [])
        ),
        top_limitations=top_terms(
            limitation
            for paper in papers
            for limitation in paper.get("normalized_limitations", [])
        ),
        top_future_work_themes=top_terms(
            theme
            for paper in papers
            for theme in paper.get("normalized_future_work", [])
        ),
    )


def analyze_gaps(
    *,
    topic: str,
    papers: list[dict],
    filters: dict,
    sources_used: list[str],
    top_k: int = 5,
) -> GapAnalysisResponse:
    current_year = datetime.now(NEPAL_TZ).year
    normalized_papers = [normalize_analysis_paper(paper) for paper in papers]

    candidates: list[CandidateGap] = []
    candidates.extend(detect_recurring_limitation_gaps(normalized_papers, current_year))
    candidates.extend(
        detect_future_work_convergence_gaps(normalized_papers, current_year)
    )
    candidates.extend(
        detect_assumption_concentration_gaps(normalized_papers, current_year)
    )
    candidates.extend(detect_evaluation_gaps(normalized_papers, current_year))

    ranked = sorted(
        merge_overlapping_gaps(candidates),
        key=lambda gap: gap.overall_score,
        reverse=True,
    )
    return GapAnalysisResponse(
        topic=topic,
        filters=filters,
        sources_used=sources_used,
        papers_analyzed=len(normalized_papers),
        evidence_summary=build_evidence_summary(normalized_papers),
        gaps=ranked[:top_k],
    )
