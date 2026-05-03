from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import List

from bson import ObjectId
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.dependencies import get_current_user
from app.schemas.synthesis import (
    SynthesisHistoryItem,
    SynthesisHistoryResponse,
    SynthesisRequest,
    SynthesisResponse,
)

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent.parent.parent / ".env")

logger = logging.getLogger(__name__)

from app.db.session import gap_reports_collection

router = APIRouter(prefix="/synthesis", tags=["Synthesis"])


#Helpers

def _is_valid_object_id(id_str: str) -> bool:
    return ObjectId.is_valid(id_str)


async def _fetch_report(report_id: str) -> dict:
    if gap_reports_collection is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not configured",
        )
    clean_id = report_id.strip()
    query: dict = {"$or": [{"report_id": clean_id}, {"_id": clean_id}]}
    if _is_valid_object_id(clean_id):
        query["$or"].append({"_id": ObjectId(clean_id)})

    doc = await gap_reports_collection.find_one(query)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report '{clean_id}' not found",
        )
    doc["report_id"] = str(doc["_id"])
    doc["_id"] = str(doc["_id"])
    return doc


def _hydrate_report(doc: dict) -> dict:

    if "visualizations" not in doc:
        from app.schemas.synthesis import VisualizationData
        doc["visualizations"] = VisualizationData().model_dump()

    if not doc.get("copy_text"):
        from app.services.synthesis.report_pipeline import _generate_copy_text
        from app.schemas.synthesis import SynthesisGap
        gaps = [SynthesisGap(**g) for g in (doc.get("gaps") or [])]
        doc["copy_text"] = _generate_copy_text(doc.get("topic", ""), gaps)

    if not doc.get("share_url"):
        doc["share_url"] = f"/synthesis/share/{doc.get('report_id', '')}"

    if not doc.get("pdf_url"):
        doc["pdf_url"] = f"/synthesis/report/{doc.get('report_id', '')}/download"

    if "success" not in doc:
        doc["success"] = True

    # Older reports may lack clusters list
    if "clusters" not in doc:
        doc["clusters"] = []

    return doc


#Routes
@router.post(
    "/gaps",
    response_model=SynthesisResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze research gaps for a single topic",
)
async def detect_gaps(
    payload: SynthesisRequest,
    current_user: dict = Depends(get_current_user),
) -> SynthesisResponse:
    from app.services.synthesis.report_pipeline import run_synthesis_pipeline
    try:
        return await run_synthesis_pipeline(payload)
    except Exception as exc:
        logger.exception("Synthesis pipeline error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Synthesis failed: {exc}",
        )


@router.post(
    "/gaps/batch",
    response_model=List[SynthesisResponse],
    status_code=status.HTTP_200_OK,
    summary="Analyze research gaps for multiple topics (max 5)",
)
async def detect_gaps_batch(
    payloads: List[SynthesisRequest],
    current_user: dict = Depends(get_current_user),
) -> List[SynthesisResponse]:
    if len(payloads) > 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Batch limit is 5 topics per request",
        )
    if not payloads:
        return []

    from app.services.synthesis.report_pipeline import run_synthesis_pipeline
    try:
        results = await asyncio.gather(
            *[run_synthesis_pipeline(p) for p in payloads],
            return_exceptions=True,
        )
        output: List[SynthesisResponse] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning("Batch item %d failed: %s", i, result)
                # Skip failed items rather than failing the entire batch
            else:
                output.append(result)
        return output
    except Exception as exc:
        logger.exception("Batch synthesis pipeline error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Batch synthesis failed: {exc}",
        )


@router.get(
    "/history",
    response_model=SynthesisHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="List past synthesis reports",
)
async def get_synthesis_history(
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
) -> SynthesisHistoryResponse:
    if gap_reports_collection is None:
        return SynthesisHistoryResponse(total=0, items=[])

    cursor = gap_reports_collection.find(
        {}, {"topic": 1, "papers_analyzed": 1, "gaps": 1, "created_at": 1}
    ).sort("created_at", -1).limit(limit)
    items: list[SynthesisHistoryItem] = []
    async for doc in cursor:
        items.append(SynthesisHistoryItem(
            report_id=str(doc["_id"]),
            topic=doc.get("topic", ""),
            papers_analyzed=doc.get("papers_analyzed", 0),
            gap_count=len(doc.get("gaps", [])),
            created_at=doc.get("created_at", ""),
        ))
    return SynthesisHistoryResponse(total=len(items), items=items)


@router.get(
    "/report/{report_id}",
    response_model=SynthesisResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve a saved synthesis report by ID",
)
async def get_synthesis_report(
    report_id: str,
    current_user: dict = Depends(get_current_user),
) -> SynthesisResponse:
    doc = _hydrate_report(await _fetch_report(report_id))
    return SynthesisResponse(**doc)


@router.get(
    "/public/report/{report_id}",
    response_model=SynthesisResponse,
    status_code=status.HTTP_200_OK,
    summary="Publicly retrieve a saved report (share links)",
)
async def get_public_synthesis_report(report_id: str) -> SynthesisResponse:
    doc = _hydrate_report(await _fetch_report(report_id))
    return SynthesisResponse(**doc)


@router.get(
    "/report/{report_id}/download",
    status_code=status.HTTP_200_OK,
    summary="Download synthesis report as PDF",
    response_class=Response,
)
async def download_synthesis_report(
    report_id: str,
    current_user: dict = Depends(get_current_user),
):
    doc = await _fetch_report(report_id)

    from app.schemas.synthesis import ClusterSummary, PatternAnalysis, SynthesisGap, VisualizationData
    from app.services.synthesis.pdf import generate_pdf_report

    pattern = PatternAnalysis(**(doc.get("pattern_analysis") or {}))
    gaps = [SynthesisGap(**g) for g in (doc.get("gaps") or [])]
    clusters = [ClusterSummary(**c) for c in (doc.get("clusters") or [])]

    viz_raw = doc.get("visualizations") or {}
    viz_fields = {k: viz_raw.get(k) for k in VisualizationData.model_fields}
    visualizations = VisualizationData(**viz_fields)

    # Reconstruct paper list with cluster tags if available
    raw_papers = doc.get("papers") or []

    pdf_bytes = generate_pdf_report(
        topic=doc.get("topic", ""),
        papers_analyzed=doc.get("papers_analyzed", 0),
        pattern=pattern,
        gaps=gaps,
        visualizations=visualizations,
        report_id=report_id,
        clusters=clusters,
        papers=raw_papers,
    )

    safe_topic = (doc.get("topic") or "report").replace(" ", "_")[:40]
    filename = f"synthesis_{safe_topic}_{report_id[:8]}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
