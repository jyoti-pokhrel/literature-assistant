from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

NEPAL_TZ = timezone(timedelta(hours=5, minutes=45))

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent.parent.parent / ".env")

from app.schemas.synthesis import (
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
from app.services.synthesis.pattern_analysis import run_pattern_analysis
from app.services.synthesis.visualization import generate_all_visualizations

logger = logging.getLogger(__name__)

from app.db.session import gap_reports_collection

async def _save_report_to_mongo(doc: dict) -> str:
    import uuid

    if gap_reports_collection is None:
        logger.warning("Database not configured; skipping DB save.")
        return str(uuid.uuid4())

    try:
        result = await gap_reports_collection.insert_one(doc)
        return str(result.inserted_id)
    except Exception as exc:
        logger.error("MongoDB save failed: %s", exc)
        return str(uuid.uuid4())


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
        # Return a graceful empty response without DB save
        import uuid
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
    reduced, labels = await loop.run_in_executor(None, reduce_and_cluster, embeddings)

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

    #Visualizations
    viz_dict = await loop.run_in_executor(
        None,
        generate_all_visualizations,
        reduced,
        labels,
        normalized_papers,
        gaps,
        pattern,
    )
    visualizations = VisualizationData(**viz_dict)

    #Generate report_id beforehand to include in links
    import uuid
    report_id = str(uuid.uuid4())
    share_url = f"/synthesis/share/{report_id}"
    pdf_url = f"/synthesis/report/{report_id}/download"
    copy_text = _generate_copy_text(request.topic, gaps)

    #Save to MongoDB
    created_at = datetime.now(NEPAL_TZ).isoformat()
    doc = {
        "_id": report_id, # Use our generated ID
        "report_id": report_id,
        "topic": request.topic,
        "filters": retrieval.filters,
        "sources_used": retrieval.sources_used,
        "papers_analyzed": len(normalized_papers),
        "pattern_analysis": pattern.model_dump(),
        "gaps": [g.model_dump() for g in gaps],
        "visualizations": viz_dict,
        "papers": [p.model_dump() for p in retrieval.papers],
        "created_at": created_at,
        "copy_text": copy_text,
        "share_url": share_url,
        "pdf_url": pdf_url,
        "success": True
    }
    
    # Save the doc - _save_report_to_mongo will handle insertion
    actual_id = await _save_report_to_mongo(doc)
    # If for some reason it returned a different ID, we should update (unlikely with our manual _id)

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
        clusters=[],
        stats={"total_gaps": len(gaps), "analyzed": len(normalized_papers)},
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
