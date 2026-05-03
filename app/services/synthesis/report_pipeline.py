from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict
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

from typing import Callable, Awaitable
from collections import Counter
import uuid



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
            "title": paper.get("title"),
            "year": paper.get("year"),
            "venue": paper.get("venue"),
            "source": paper.get("source"),
            "x": round(float(point[0]), 4) if len(point) > 0 else 0.0,
            "y": round(float(point[1]), 4) if len(point) > 1 else 0.0,
        })

    # fallback: all papers in single cluster
    if not cluster_map and normalized_papers:
        cluster_map[0] = [{
            "paper_id": p.get("paper_id"),
            "title": p.get("title"),
            "year": p.get("year"),
            "venue": p.get("venue"),
            "source": p.get("source"),
            "x": 0.0,
            "y": 0.0,
        } for p in normalized_papers]

    gaps_by_cluster: dict[int, list[dict]] = {}

    for gap in gaps:
        gaps_by_cluster.setdefault(gap.cluster_id, []).append({
            "gap_id": gap.gap_id,
            "gap_title": gap.gap_title,
            "confidence_score": gap.confidence_score,
            "validation_status": gap.citation_validation.get("status")
            if gap.citation_validation else "unknown",
        })

    clusters: list[dict] = []

    for cluster_id, papers in sorted(cluster_map.items()):
        xs = [p["x"] for p in papers]
        ys = [p["y"] for p in papers]

        clusters.append({
            "cluster_id": cluster_id,
            "paper_count": len(papers),
            "centroid": {
                "x": round(sum(xs) / len(xs), 4) if xs else 0.0,
                "y": round(sum(ys) / len(ys), 4) if ys else 0.0,
            },
            "top_terms": _cluster_top_terms(normalized_papers, cluster_id, raw_labels),
            "papers": papers,
            "gaps": gaps_by_cluster.get(cluster_id, []),
        })

    return clusters



def _cluster_top_terms(normalized_papers: list[dict], cluster_id: int, labels) -> list[str]:
    counter: Counter[str] = Counter()

    raw_labels = labels.tolist() if hasattr(labels, "tolist") else labels

    for paper, label in zip(normalized_papers, raw_labels):
        if int(label) != cluster_id:
            continue

        for key in (
            "normalized_method",
            "normalized_datasets",
            "normalized_metrics",
            "normalized_limitations",
        ):
            value = paper.get(key)

            if isinstance(value, list):
                counter.update(v for v in value if v)
            elif value:
                counter[value] += 1

    return [term for term, _ in counter.most_common(5)]



async def _save_report_to_mongo(doc: dict) -> str:
    return str(uuid.uuid4())

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

        summaries.append(ClusterSummary(
            cluster_id=cluster_id,
            theme_label=themes.get("theme_label", f"Cluster {cluster_id}"),
            paper_count=len(papers),
            top_limitations=themes.get("top_limitations", []),
            top_future_work=themes.get("top_future_work", []),
            gap_id=gap_by_cluster.get(cluster_id),
        ))

    return sorted(summaries, key=lambda s: s.cluster_id)

    loop = asyncio.get_event_loop()
    await _emit_progress(
        progress_callback,
        stage="prepare",
        label="Understanding your topic",
        detail="Cleaning the query and applying your filters.",
        progress=6,
    )

sources = ", ".join(enabled_sources)

await _emit_progress(
    progress_callback,
    stage="retrieval",
    label="Searching trusted paper indexes",
    detail=f"Querying {sources}.",
    progress=14,
)
    retrieval = await retrieve_papers(
        request.topic,
        year=request.year,
        venue=request.venue,
        max_results=request.max_results,
    )
    raw_papers = build_analysis_papers(retrieval.papers)
    await _emit_progress(
        progress_callback,
        stage="retrieval_done",
        label=f"Found {len(raw_papers)} candidate papers",
        detail=f"Sources used: {', '.join(retrieval.sources_used) or 'none'}.",
        progress=28,
        meta={"paper_count": len(raw_papers), "sources_used": retrieval.sources_used},
    )
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
    await _emit_progress(
        progress_callback,
        stage="evidence",
        label="Reading evidence signals",
        detail="Extracting methods, datasets, metrics, limitations, and future-work clues.",
        progress=38,
    )
    normalized_papers: list[dict] = await loop.run_in_executor(
        None, lambda: [normalize_analysis_paper(p) for p in raw_papers]
    )

    #Embeddings
    await _emit_progress(
        progress_callback,
        stage="embedding",
        label="Mapping papers by meaning",
        detail="Creating semantic embeddings so related papers can be grouped.",
        progress=50,
    )
    embeddings = await loop.run_in_executor(None, generate_embeddings, normalized_papers)

    #UMAP + HDBSCAN
await _emit_progress(
    progress_callback,
    stage="clustering",
    label="Grouping research themes",
    detail="Reducing dimensions and clustering papers into topic neighborhoods.",
    progress=60,
)

reduced_2d, reduced_nd, labels = await loop.run_in_executor(
    None,
    reduce_and_cluster,
    embeddings,
)


cluster_map: dict[int, list[dict]] = defaultdict(list)

for paper, label in zip(normalized_papers, labels.tolist()):
    cluster_id = int(label)

    if cluster_id != -1:
        cluster_map[cluster_id].append(paper)

# fallback cluster
if not cluster_map:
    cluster_map[0] = normalized_papers


for paper, label in zip(normalized_papers, labels.tolist()):
    paper["_cluster_id"] = int(label) if label != -1 else 0


cluster_themes: dict[int, dict] = await loop.run_in_executor(
    None,
    lambda: {
        cid: extract_cluster_themes(papers)
        for cid, papers in cluster_map.items()
    },
)

    #Pattern analysis
    await _emit_progress(
        progress_callback,
        stage="patterns",
        label="Finding literature patterns",
        detail="Checking repeated methods, datasets, metrics, limitations, and trends.",
        progress=70,
    )
    pattern: PatternAnalysis = await loop.run_in_executor(
        None, run_pattern_analysis, normalized_papers
    )

    #LLM gap reasoning
    await _emit_progress(
        progress_callback,
        stage="gaps",
        label="Drafting research gaps",
        detail="Turning repeated weaknesses into specific, evidence-backed gap statements.",
        progress=80,
    )
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
    await _emit_progress(
        progress_callback,
        stage="visualizations",
        label="Preparing your report",
        detail="Building charts, cluster summaries, citation checks, and export data.",
        progress=90,
    )
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
    visualizations = VisualizationData(**viz_dict)
    clusters = _build_cluster_dashboard(normalized_papers, labels, reduced, gaps)

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
        "clusters": clusters,
        "papers": [p.model_dump() for p in retrieval.papers],
        "created_at": created_at,
        "copy_text": copy_text,
        "share_url": share_url,
        "pdf_url": pdf_url,
        "success": True,
    }
# Save the report to MongoDB
await _save_report_to_mongo(doc)


dataset_path = append_gap_dataset_record({
    "report_id": report_id,
    "topic": request.topic,
    "filters": retrieval.filters,
    "sources_used": retrieval.sources_used,
    "created_at": created_at,
    "papers": [p.model_dump() for p in retrieval.papers],
    "normalized_papers": normalized_papers,
    "pattern_analysis": pattern.model_dump(),
    "clusters": clusters,
    "gaps": [g.model_dump() for g in gaps],
    "visualizations_present": {
        key: bool(value) for key, value in viz_dict.items()
    },
})


await _emit_progress(
    progress_callback,
    stage="complete",
    label="Report ready",
    detail="The synthesis is complete.",
    progress=100,
)

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
stats={
    "total_gaps": len(gaps),
    "analyzed": len(normalized_papers),
    "clusters": len(clusters),
    "dataset_path": dataset_path,
}
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
