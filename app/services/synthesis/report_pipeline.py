from __future__ import annotations

import asyncio
import logging
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Awaitable, Callable

NEPAL_TZ = timezone(timedelta(hours=5, minutes=45))

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent.parent.parent / ".env")

from app.schemas.synthesis import (
    ClusterSummary,
    PatternAnalysis,
    SynthesisGap,
    SynthesisRequest,
    SynthesisResponse,
    VisualizationData,
)
from app.services.analysis.normalization import normalize_analysis_paper
from app.services.orchestration.pipeline import build_analysis_papers
from app.services.retrieval.fetcher import retrieve_papers
from app.services.synthesis.clustering import reduce_and_cluster
from app.services.synthesis.dataset_builder import append_gap_dataset_record
from app.services.synthesis.embeddings import generate_embeddings
from app.services.synthesis.gap_generator import generate_all_gaps
from app.services.synthesis.pattern_analysis import extract_cluster_themes, run_pattern_analysis
from app.services.synthesis.visualization import generate_all_visualizations

logger = logging.getLogger(__name__)

from app.db.session import gap_reports_collection


ProgressCallback = Callable[[dict], Awaitable[None]]


async def _emit_progress(progress_callback: ProgressCallback | None, **event) -> None:
    if progress_callback is not None:
        await progress_callback(event)


def _build_cluster_dashboard(
    normalized_papers: list[dict],
    labels,
    reduced,
    gaps: list[SynthesisGap],
) -> list[dict]:

    cluster_map: dict[int, list[dict]] = {}

    raw_labels = labels.tolist() if hasattr(labels, "tolist") else labels

    for index, (paper, label) in enumerate(zip(normalized_papers, raw_labels)):
        cluster_id = int(label)
        if cluster_id == -1:
            continue

        point = reduced[index].tolist() if hasattr(reduced[index], "tolist") else list(reduced[index])

        cluster_map.setdefault(cluster_id, []).append({
            "paper_id": paper.get("paper_id"),
            "title":    paper.get("title"),
            "year":     paper.get("year"),
            "venue":    paper.get("venue"),
            "source":   paper.get("source"),
            "x": round(float(point[0]), 4) if len(point) > 0 else 0.0,
            "y": round(float(point[1]), 4) if len(point) > 1 else 0.0,
        })

    if not cluster_map and normalized_papers:
        cluster_map[0] = [{
            "paper_id": p.get("paper_id"),
            "title":    p.get("title"),
            "year":     p.get("year"),
            "venue":    p.get("venue"),
            "source":   p.get("source"),
            "x": 0.0,
            "y": 0.0,
        } for p in normalized_papers]

    gaps_by_cluster: dict[int, list[dict]] = {}
    for gap in gaps:
        # Filter out hallucinated or already addressed gaps from the dashboard/map
        if (gap.llm_verification.get("status", "").lower() == "hallucinated") or \
           (gap.citation_validation.get("status", "").lower() == "hallucinated") or \
           (gap.cross_paper_validation.get("status", "").lower() == "potentially_addressed"):
            continue

        gaps_by_cluster.setdefault(gap.cluster_id, []).append({
            "gap_id":            gap.gap_id,
            "gap_title":         gap.gap_title,
            "confidence_score":  gap.confidence_score,
            "validation_status": gap.citation_validation.get("status")
                                  if gap.citation_validation else "unknown",
        })

    clusters: list[dict] = []
    for cluster_id, papers in sorted(cluster_map.items()):
        xs = [p["x"] for p in papers]
        ys = [p["y"] for p in papers]
        clusters.append({
            "cluster_id":   cluster_id,
            "paper_count":  len(papers),
            "centroid": {
                "x": round(sum(xs) / len(xs), 4) if xs else 0.0,
                "y": round(sum(ys) / len(ys), 4) if ys else 0.0,
            },
            "top_terms": _cluster_top_terms(normalized_papers, cluster_id, raw_labels),
            "papers": papers,
            "gaps":   gaps_by_cluster.get(cluster_id, []),
        })

    return clusters


def _cluster_top_terms(normalized_papers: list[dict], cluster_id: int, labels) -> list[str]:
    counter: Counter[str] = Counter()
    raw_labels = labels.tolist() if hasattr(labels, "tolist") else labels
    for paper, label in zip(normalized_papers, raw_labels):
        if int(label) != cluster_id:
            continue
        for key in ("normalized_method", "normalized_datasets", "normalized_metrics", "normalized_limitations"):
            value = paper.get(key)
            if isinstance(value, list):
                counter.update(v for v in value if v)
            elif value:
                counter[value] += 1
    return [term for term, _ in counter.most_common(5)]


async def _save_report_to_mongo(doc: dict) -> str:
    if gap_reports_collection is None:
        logger.warning("Database not configured; skipping DB save.")
        return str(uuid.uuid4())
    try:
        result = await gap_reports_collection.insert_one(doc)
        return str(result.inserted_id)
    except Exception as exc:
        logger.error("MongoDB save failed: %s", exc)
        return str(uuid.uuid4())


def _build_cluster_summaries(
    cluster_map: dict[int, list[dict]],
    cluster_themes: dict[int, dict],
    gaps: list[SynthesisGap],
) -> list[ClusterSummary]:

    gap_by_cluster = {g.cluster_id: g.gap_id for g in gaps}
    summaries: list[ClusterSummary] = []

    for cluster_id, papers in cluster_map.items():
        themes = cluster_themes.get(cluster_id, {})
        label  = themes.get("theme_label", "")
        if not label or "unspecified" in label.lower():
            label = f"Research Theme #{cluster_id}"

        lims = themes.get("top_limitations", [])
        if not lims or not lims[0] or "unspecified" in str(lims[0]).lower():
            lims = ["Insufficient data available for targeted analysis."]

        trend_status = themes.get("trend_status", "Established")

        summaries.append(ClusterSummary(
            cluster_id=cluster_id,
            theme_label=label,
            paper_count=len(papers),
            top_limitations=lims,
            top_future_work=themes.get("top_future_work", []),
            gap_id=gap_by_cluster.get(cluster_id),
            trend_status=trend_status,
        ))

    return sorted(summaries, key=lambda s: s.cluster_id)


#Main pipeline

async def run_synthesis_pipeline(
    request: SynthesisRequest,
    progress_callback: ProgressCallback | None = None,
) -> SynthesisResponse:
    loop = asyncio.get_event_loop()

    #: prepare
    await _emit_progress(progress_callback, stage="prepare",
        label="Understanding your topic",
        detail="Cleaning the query and applying your filters.", progress=6)

    sources = "semantic_scholar, openalex, arxiv"

    #retrieval
    await _emit_progress(progress_callback, stage="retrieval",
        label="Searching trusted paper indexes",
        detail=f"Querying {sources}.", progress=14)

    retrieval = await retrieve_papers(
        request.topic,
        year=request.year,
        venue=request.venue,
        strict_venue=request.strict_venue,
        max_results=request.max_results,
    )
    raw_papers = build_analysis_papers(retrieval.papers)

    await _emit_progress(progress_callback, stage="retrieval_done",
        label=f"Found {len(raw_papers)} candidate papers",
        detail=f"Sources used: {', '.join(retrieval.sources_used) or 'none'}.",
        progress=28,
        meta={"paper_count": len(raw_papers), "sources_used": retrieval.sources_used})

    if not raw_papers:
        return SynthesisResponse(
            report_id=str(uuid.uuid4()),
            topic=request.topic,
            filters=retrieval.filters,
            sources_used=retrieval.sources_used,
            sources_count=len(retrieval.sources_used),
            papers_analyzed=0,
            pattern_analysis=PatternAnalysis(),
            gaps=[],
            clusters=[],
            stats={"total_gaps": 0, "analyzed": 0},
            visualizations=VisualizationData(),
            created_at=datetime.now(NEPAL_TZ).isoformat(),
            papers=[],
        )

    #normalise
    await _emit_progress(progress_callback, stage="evidence",
        label="Reading evidence signals",
        detail="Extracting methods, datasets, metrics, limitations, and future-work clues.",
        progress=38)

    normalized_papers: list[dict] = await loop.run_in_executor(
        None, lambda: [normalize_analysis_paper(p) for p in raw_papers]
    )

    #embeddings 
    await _emit_progress(progress_callback, stage="embedding",
        label="Mapping papers by meaning",
        detail="Creating semantic embeddings so related papers can be grouped.",
        progress=50)


    normalized_papers.sort(key=lambda p: (p.get("paper_id") or p.get("title", "")))

    embeddings = await loop.run_in_executor(None, generate_embeddings, normalized_papers)

    #clustering
    await _emit_progress(progress_callback, stage="clustering",
        label="Grouping research themes",
        detail="Reducing dimensions and clustering papers into topic neighbourhoods.",
        progress=60)

    import functools

    dynamic_min_cluster = max(2, len(normalized_papers) // 20)
    reduced_2d, reduced_nd, labels, cluster_accuracy = await loop.run_in_executor(
        None, functools.partial(reduce_and_cluster, embeddings, min_cluster_size=dynamic_min_cluster)
    )

    cluster_map: dict[int, list[dict]] = defaultdict(list)
    for paper, label in zip(normalized_papers, labels.tolist()):
        if int(label) != -1:
            cluster_map[int(label)].append(paper)
    if not cluster_map:
        cluster_map[0] = normalized_papers

    for paper, label in zip(normalized_papers, labels.tolist()):
        paper["_cluster_id"] = int(label) if label != -1 else 0

    #patterns + themes (heuristic, fast)
    await _emit_progress(progress_callback, stage="patterns",
        label="Finding literature patterns",
        detail="Checking repeated methods, datasets, metrics, limitations, and trends.",
        progress=70)

    heuristic_themes: dict[int, dict] = {
        cid: extract_cluster_themes(papers)
        for cid, papers in cluster_map.items()
    }

    # Run pattern analysis concurrently with gap generation setup
    pattern_future = loop.run_in_executor(None, run_pattern_analysis, normalized_papers)

    #gaps (LLM, parallelised across clusters)
    await _emit_progress(progress_callback, stage="gaps",
        label="Drafting research gaps",
        detail="Turning repeated weaknesses into specific, evidence-backed gap statements.",
        progress=80)

    pattern = await pattern_future   # make sure pattern is ready before passing


    gaps, llm_theme_labels = await generate_all_gaps(
        normalized_papers,
        labels.tolist(),
        request.topic,
        pattern,
        request.top_k_gaps,
    )

    # Merge LLM theme labels into heuristic themes (no extra LLM call needed)
    for cid, llm_label in llm_theme_labels.items():
        if cid in heuristic_themes and llm_label:
            existing = heuristic_themes[cid].get("theme_label", "")
            if not existing or "unspecified" in existing.lower():
                heuristic_themes[cid]["theme_label"] = llm_label

    cluster_themes = heuristic_themes   # already healed inline ↑

    #visualisations + cluster summaries (parallel)
    await _emit_progress(progress_callback, stage="visualizations",
        label="Preparing your report",
        detail="Building charts, cluster summaries, citation checks, and export data.",
        progress=90)

    cluster_summaries_future = loop.run_in_executor(
        None, _build_cluster_summaries, cluster_map, cluster_themes, gaps,
    )
    # Filter out hallucinated/addressed gaps for visualizations
    valid_viz_gaps = [
        g for g in gaps 
        if (g.llm_verification.get("status", "").lower() != "hallucinated") and 
           (g.citation_validation.get("status", "").lower() != "hallucinated") and
           (g.cross_paper_validation.get("status", "").lower() != "potentially_addressed")
    ]

    viz_dict_future = loop.run_in_executor(
        None, generate_all_visualizations,
        reduced_2d, labels, normalized_papers, valid_viz_gaps, pattern, cluster_themes,
    )
    cluster_dashboard_future = loop.run_in_executor(
        None, _build_cluster_dashboard,
        normalized_papers, labels, reduced_2d, gaps,
    )

    cluster_summaries, viz_dict, cluster_dashboard = await asyncio.gather(
        cluster_summaries_future, viz_dict_future, cluster_dashboard_future
    )

    visualizations = VisualizationData(**{
        k: viz_dict.get(k) for k in VisualizationData.model_fields
    })

    # Attach paper coordinates to cluster summaries
    dashboard_by_id = {d["cluster_id"]: d for d in cluster_dashboard}
    for summary in cluster_summaries:
        summary.papers = dashboard_by_id.get(summary.cluster_id, {}).get("papers", [])

    #Assemble metadata
    report_id  = str(uuid.uuid4())
    share_url  = f"/synthesis/share/{report_id}"
    pdf_url    = f"/synthesis/report/{report_id}/download"
    copy_text  = _generate_copy_text(request.topic, gaps)
    created_at = datetime.now(NEPAL_TZ).isoformat()

    doc = {
        "_id":              report_id,
        "report_id":        report_id,
        "topic":            request.topic,
        "filters":          retrieval.filters,
        "sources_used":     retrieval.sources_used,
        "papers_analyzed":  len(normalized_papers),
        "pattern_analysis": pattern.model_dump(),
        "gaps":             [g.model_dump() for g in gaps],
        "clusters":         cluster_dashboard,
        "visualizations":   viz_dict,
        "papers":           [p.model_dump() for p in retrieval.papers],
        "created_at":       created_at,
        "copy_text":        copy_text,
        "share_url":        share_url,
        "pdf_url":          pdf_url,
        "success":          True,
    }

    # Ensure all dictionary keys (e.g. from Python dicts) are stringified for MongoDB
    import json
    doc = json.loads(json.dumps(doc))

    dataset_record = {
        "report_id":            report_id,
        "topic":                request.topic,
        "filters":              retrieval.filters,
        "sources_used":         retrieval.sources_used,
        "created_at":           created_at,
        "papers":               [p.model_dump() for p in retrieval.papers],
        "normalized_papers":    normalized_papers,
        "pattern_analysis":     pattern.model_dump(),
        "clusters":             cluster_dashboard,
        "gaps":                 [g.model_dump() for g in gaps],
        "visualizations_present": {k: bool(v) for k, v in viz_dict.items()},
    }

    #Fire-and-forget: DB save + dataset write
    async def _background_saves() -> None:
        try:
            await _save_report_to_mongo(doc)
        except Exception as exc:
            logger.error("Background MongoDB save failed: %s", exc)
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, append_gap_dataset_record, dataset_record
            )
        except Exception as exc:
            logger.error("Background dataset save failed: %s", exc)

    asyncio.create_task(_background_saves())

    await _emit_progress(progress_callback, stage="complete",
        label="Report ready",
        detail="The synthesis is complete.", progress=100)

    return SynthesisResponse(
        success=True,
        report_id=report_id,
        share_url=share_url,
        copy_text=copy_text,
        topic=request.topic,
        filters=retrieval.filters,
        sources_used=retrieval.sources_used,
        sources_count=len(retrieval.sources_used),
        papers_analyzed=len(normalized_papers),
        pattern_analysis=pattern,
        gaps=gaps,
        clusters=cluster_summaries,
        stats={
            "total_gaps": len(gaps),
            "analyzed":   len(normalized_papers),
            "clusters":   len(cluster_summaries),
            "cluster_accuracy": round(cluster_accuracy, 2)
        },
        visualizations=visualizations,
        pdf_url=pdf_url,
        created_at=created_at,
        papers=[p.model_dump() for p in retrieval.papers],
    )


def _generate_copy_text(topic: str, gaps: list[SynthesisGap]) -> str:
    lines = [f"# Synthesis Report: {topic}\n"]
    
    # Filter out hallucinated and non-novel gaps
    valid_gaps = [
        g for g in gaps 
        if not ((g.llm_verification.get("status", "").lower() == "hallucinated") or 
                (g.citation_validation.get("status", "").lower() == "hallucinated") or
                (g.cross_paper_validation.get("status", "").lower() == "potentially_addressed"))
    ]
    
    for idx, gap in enumerate(valid_gaps, 1):
        lines.append(f"## {idx}. {gap.gap_title}")
        lines.append(f"**Description:** {gap.description}")
        lines.append(f"**What fails:** {gap.what_fails}")
        lines.append(f"**Missing piece:** {gap.missing_piece}")
        lines.append(f"**Proposed direction:** {gap.proposed_direction}")
        if gap.citations:
            lines.append("\n**Sources:**")
            for c in gap.citations:
                title = getattr(c, "title", "Unknown")
                year  = getattr(c, "year", "N/A")
                lines.append(f"- {title} ({year})")
        lines.append("\n")
    return "\n".join(lines)
