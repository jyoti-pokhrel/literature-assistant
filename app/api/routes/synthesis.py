from __future__ import annotations

import logging
import asyncio
import json
import os
from pathlib import Path

from bson import ObjectId
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response, StreamingResponse

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


# Helpers

def _is_valid_object_id(id_str: str) -> bool:
    return ObjectId.is_valid(id_str)


async def _fetch_report(report_id: str) -> dict:
    if gap_reports_collection is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not configured",
        )
    
    # Clean ID and try multiple fields/formats
    clean_id = report_id.strip()
    query = {"$or": [
        {"report_id": clean_id},
        {"_id": clean_id}
    ]}
    
    if _is_valid_object_id(clean_id):
        query["$or"].append({"_id": ObjectId(clean_id)})
        
    doc = await gap_reports_collection.find_one(query)

    if not doc:
        # Fallback for UUIDs that might be stored as report_id but searched via clean_id
        # (Already covered by $or, but added logging context if needed)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report '{clean_id}' not found",
        )
    
    # Map MongoDB _id to report_id for Pydantic schema consistency
    doc["report_id"] = str(doc["_id"])
    doc["_id"] = str(doc["_id"])
    return doc

# Routes

@router.post(
    "/gaps",
    response_model=SynthesisResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze gaps",
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
    "/gaps/stream",
    status_code=status.HTTP_200_OK,
    summary="Analyze gaps with streamed progress",
)
async def stream_detect_gaps(
    payload: SynthesisRequest,
    current_user: dict = Depends(get_current_user),
) -> StreamingResponse:
    from app.services.synthesis.report_pipeline import run_synthesis_pipeline

    queue: asyncio.Queue[dict] = asyncio.Queue()

    async def progress_callback(event: dict) -> None:
        await queue.put({"type": "progress", **event})

    async def run_pipeline() -> None:
        try:
            result = await run_synthesis_pipeline(payload, progress_callback=progress_callback)
            await queue.put({"type": "result", "data": result.model_dump()})
        except Exception as exc:
            logger.exception("Synthesis stream error: %s", exc)
            await queue.put({"type": "error", "detail": f"Synthesis failed: {exc}"})
        finally:
            await queue.put({"type": "done"})

    async def event_stream():
        task = asyncio.create_task(run_pipeline())
        try:
            while True:
                event = await queue.get()
                yield json.dumps(event, default=str) + "\n"
                if event.get("type") == "done":
                    break
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.get(
    "/history",
    response_model=SynthesisHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="List past reports",
)
async def get_synthesis_history(
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
) -> SynthesisHistoryResponse:
    if gap_reports_collection is None:
        return SynthesisHistoryResponse(total=0, items=[])
    
    cursor = gap_reports_collection.find({}, {"topic": 1, "papers_analyzed": 1, "gaps": 1, "created_at": 1}).sort("created_at", -1).limit(limit)
    items: list[SynthesisHistoryItem] = []
    async for doc in cursor:
        items.append(
            SynthesisHistoryItem(
                report_id=str(doc["_id"]),
                topic=doc.get("topic", ""),
                papers_analyzed=doc.get("papers_analyzed", 0),
                gap_count=len(doc.get("gaps", [])),
                created_at=doc.get("created_at", ""),
            )
        )
    return SynthesisHistoryResponse(total=len(items), items=items)


@router.get(
    "/report/{report_id}",
    response_model=SynthesisResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve a saved report by ID",
)
async def get_synthesis_report(
    report_id: str,
    current_user: dict = Depends(get_current_user),
) -> SynthesisResponse:
    doc = await _fetch_report(report_id)
    
    # Ensure all required fields exist for Pydantic validation
    if "visualizations" not in doc:
        from app.schemas.synthesis import VisualizationData
        doc["visualizations"] = VisualizationData().model_dump()

    # Populate missing fields for older reports
    if not doc.get("copy_text"):
        from app.services.synthesis.report_pipeline import _generate_copy_text
        from app.schemas.synthesis import SynthesisGap
        gaps = [SynthesisGap(**g) for g in (doc.get("gaps") or [])]
        doc["copy_text"] = _generate_copy_text(doc.get("topic", ""), gaps)
    
    if not doc.get("share_url"):
        doc["share_url"] = f"/synthesis/share/{report_id}"
    
    if not doc.get("pdf_url"):
        doc["pdf_url"] = f"/synthesis/report/{report_id}/download"
    
    if "success" not in doc:
        doc["success"] = True

    return SynthesisResponse(**doc)


@router.get(
    "/public/report/{report_id}",
    response_model=SynthesisResponse,
    status_code=status.HTTP_200_OK,
    summary="Publicly retrieve a saved report by ID (Share links)",
)
async def get_public_synthesis_report(
    report_id: str,
) -> SynthesisResponse:
    doc = await _fetch_report(report_id)
    
    # Ensure all required fields exist for Pydantic validation
    if "visualizations" not in doc:
        from app.schemas.synthesis import VisualizationData
        doc["visualizations"] = VisualizationData().model_dump()

    # Populate missing fields for older reports
    if not doc.get("copy_text"):
        from app.services.synthesis.report_pipeline import _generate_copy_text
        from app.schemas.synthesis import SynthesisGap
        gaps = [SynthesisGap(**g) for g in (doc.get("gaps") or [])]
        doc["copy_text"] = _generate_copy_text(doc.get("topic", ""), gaps)
    
    if not doc.get("share_url"):
        doc["share_url"] = f"/synthesis/share/{report_id}"
    
    if not doc.get("pdf_url"):
        doc["pdf_url"] = f"/synthesis/report/{report_id}/download"
    
    if "success" not in doc:
        doc["success"] = True

    return SynthesisResponse(**doc)


@router.get(
    "/report/{report_id}/download",
    status_code=status.HTTP_200_OK,
    summary="Download report as PDF",
    response_class=Response,
)
async def download_synthesis_report(
    report_id: str,
    current_user: dict = Depends(get_current_user),
):
    doc = await _fetch_report(report_id)

    from app.schemas.synthesis import PatternAnalysis, SynthesisGap, VisualizationData
    from app.services.synthesis.pdf import generate_pdf_report

    # Reconstruct Pydantic objects from stored dicts
    pattern = PatternAnalysis(**(doc.get("pattern_analysis") or {}))
    gaps = [SynthesisGap(**g) for g in (doc.get("gaps") or [])]
    viz_raw = doc.get("visualizations") or {}
    # Only pass known fields to VisualizationData
    viz_fields = {k: viz_raw.get(k) for k in VisualizationData.model_fields}
    visualizations = VisualizationData(**viz_fields)

    pdf_bytes = generate_pdf_report(
        topic=doc.get("topic", ""),
        papers_analyzed=doc.get("papers_analyzed", 0),
        pattern=pattern,
        gaps=gaps,
        visualizations=visualizations,
        report_id=report_id,
    )

    safe_topic = (doc.get("topic") or "report").replace(" ", "_")[:40]
    filename = f"synthesis_{safe_topic}_{report_id[:8]}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
