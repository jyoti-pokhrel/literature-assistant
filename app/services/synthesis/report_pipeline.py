from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

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
from app.services.synthesis.embeddings import generate_embeddings
from app.services.synthesis.gap_generator import generate_all_gaps
from app.services.synthesis.pattern_analysis import extract_cluster_themes, run_pattern_analysis
from app.services.synthesis.visualization import generate_all_visualizations

logger = logging.getLogger(__name__)

from app.db.session import gap_reports_collection


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
    """Build ClusterSummary objects from cluster data, linking each to its gap."""
    gap_by_cluster = {g.cluster_id: g.gap_id for g in gaps}
    summaries: list[ClusterSummary] = []
    for cluster_id, papers in cluster_map.items():
        themes = cluster_themes.get(cluster_id, {})
        summaries.append(ClusterSummary(
            cluster_id=cluster_id,
            theme_label=themes.get("theme_label", f"Cluster {cluster_id}"),
            paper_count=len(papers),
            top_limitations=themes.get("top_limitations", []),
            top_future_work=themes.get("top_future_work", []),
            gap_id=gap_by_cluster.get(cluster_id),
        ))
    return sorted(summaries, key=lambda s: s.cluster_id)


async def run_synthesis_pipeline(request: SynthesisRequest) -> SynthesisResponse:

    loop = asyncio.get_event_loop()

    #Retrieve papers
    retrieval = await retrieve_papers(
        request.topic,
        year=request.year,
        venue=request.venue,
        max_results=request.max_results,
    )
    raw_papers = build_analysis_papers(retrieval.papers)
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

    #Normalize
    normalized_papers: list[dict] = await loop.run_in_executor(
        None, lambda: [normalize_analysis_paper(p) for p in raw_papers]
    )

    #Embeddings
    embeddings = await loop.run_in_executor(None, generate_embeddings, normalized_papers)

    #UMAP + HDBSCAN
    reduced_2d, reduced_nd, labels = await loop.run_in_executor(
        None, reduce_and_cluster, embeddings
    )

    #Build cluster map
    cluster_map: dict[int, list[dict]] = defaultdict(list)
    for paper, label in zip(normalized_papers, labels.tolist()):
        if label != -1:
            cluster_map[int(label)].append(paper)
    if not cluster_map:
        cluster_map[0] = normalized_papers

    # Tag each paper with its cluster id for paper-to-gap mapping in PDF
    for paper, label in zip(normalized_papers, labels.tolist()):
        paper["_cluster_id"] = int(label) if label != -1 else 0

    #Per-cluster theme extraction
    cluster_themes: dict[int, dict] = await loop.run_in_executor(
        None,
        lambda: {cid: extract_cluster_themes(cprs) for cid, cprs in cluster_map.items()},
    )

    #Pattern analysis
    pattern: PatternAnalysis = await loop.run_in_executor(
        None, run_pattern_analysis, normalized_papers
    )

    #LLM gap reasoning
    gaps: list[SynthesisGap] = await loop.run_in_executor(
        None,
        generate_all_gaps,
        normalized_papers,
        labels.tolist(),
        request.topic,
        pattern,
        request.top_k_gaps,
    )

    #Cluster summaries
    clusters: list[ClusterSummary] = await loop.run_in_executor(
        None,
        _build_cluster_summaries,
        cluster_map,
        cluster_themes,
        gaps,
    )

    #Visualizations
    viz_dict = await loop.run_in_executor(
        None,
        generate_all_visualizations,
        reduced_2d,
        labels,
        normalized_papers,
        gaps,
        pattern,
        cluster_themes,
    )
    visualizations = VisualizationData(**{
        k: viz_dict.get(k) for k in VisualizationData.model_fields
    })

    #IDs and share links
    report_id = str(uuid.uuid4())
    share_url = f"/synthesis/share/{report_id}"
    pdf_url = f"/synthesis/report/{report_id}/download"
    copy_text = _generate_copy_text(request.topic, gaps)
    created_at = datetime.now(NEPAL_TZ).isoformat()

    #Save to MongoDB
    doc = {
        "_id": report_id,
        "report_id": report_id,
        "topic": request.topic,
        "filters": retrieval.filters,
        "sources_used": retrieval.sources_used,
        "papers_analyzed": len(normalized_papers),
        "pattern_analysis": pattern.model_dump(),
        "gaps": [g.model_dump() for g in gaps],
        "clusters": [c.model_dump() for c in clusters],
        "visualizations": viz_dict,
        "papers": [p.model_dump() for p in retrieval.papers],
        "created_at": created_at,
        "copy_text": copy_text,
        "share_url": share_url,
        "pdf_url": pdf_url,
        "success": True,
    }
    await _save_report_to_mongo(doc)

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
        clusters=clusters,
        stats={"total_gaps": len(gaps), "analyzed": len(normalized_papers), "clusters": len(clusters)},
        visualizations=visualizations,
        pdf_url=pdf_url,
        created_at=created_at,
        papers=[p.model_dump() for p in retrieval.papers],
    )


def _generate_copy_text(topic: str, gaps: list[SynthesisGap]) -> str:
    lines = [f"# Synthesis Report: {topic}\n"]
    for idx, gap in enumerate(gaps, 1):
        lines.append(f"## {idx}. {gap.gap_title}")
        lines.append(f"**Description:** {gap.description}")
        lines.append(f"**What fails:** {gap.what_fails}")
        lines.append(f"**Missing piece:** {gap.missing_piece}")
        lines.append(f"**Proposed direction:** {gap.proposed_direction}")
        if gap.citations:
            lines.append("\n**Sources:**")
            for c in gap.citations:
                title = getattr(c, "title", "Unknown")
                year = getattr(c, "year", "N/A")
                lines.append(f"- {title} ({year})")
        lines.append("\n")
    return "\n".join(lines)
