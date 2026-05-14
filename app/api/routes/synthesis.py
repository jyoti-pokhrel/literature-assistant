from __future__ import annotations

import asyncio
import logging
import json
import os
from pathlib import Path
from typing import List

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response, StreamingResponse

from app.api.dependencies import require_researcher, require_viewer
from app.db.session import get_db
from app.schemas.synthesis import (
    SynthesisHistoryItem,
    SynthesisHistoryResponse,
    SynthesisRequest,
    SynthesisResponse,
    SynthesisJobStatus,
    JobStatusEnum,
)
import datetime
from app.services.retrieval.history import save_search_history

# Global job store for tracking background tasks
# In production, this could be moved to Redis or MongoDB TTL collection
job_store: Dict[str, SynthesisJobStatus] = {}


def _get_gap_reports_collection():
    """Get gap_reports collection dynamically at request time."""
    db = get_db()
    return db.gap_reports if db else None

router = APIRouter(prefix="/synthesis", tags=["Synthesis"])


#Helpers

def _is_valid_object_id(id_str: str) -> bool:
    return ObjectId.is_valid(id_str)


async def _fetch_report(report_id: str) -> dict:
    collection = _get_gap_reports_collection()
    if collection is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not configured",
        )
    clean_id = report_id.strip()
    query: dict = {"$or": [{"report_id": clean_id}, {"_id": clean_id}]}
    if _is_valid_object_id(clean_id):
        query["$or"].append({"_id": ObjectId(clean_id)})

    doc = await collection.find_one(query)
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
    summary="Analyze research gaps for a single topic (Synchronous)",
)
async def detect_gaps(
    payload: SynthesisRequest,
    current_user: dict = Depends(require_researcher),
) -> SynthesisResponse:
    from app.services.synthesis.report_pipeline import run_synthesis_pipeline
    try:
        return await run_synthesis_pipeline(payload, username=current_user["username"])
    except Exception as exc:
        logger.exception("Synthesis pipeline error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Synthesis failed: {exc}",
        )

@router.post(
    "/gaps/async",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Analyze research gaps in the background (Asynchronous)",
)
async def detect_gaps_async(
    payload: SynthesisRequest,
    current_user: dict = Depends(require_researcher),
):
    from app.services.synthesis.report_pipeline import run_synthesis_pipeline
    import uuid
    
    job_id = str(uuid.uuid4())
    now = datetime.datetime.now().isoformat()
    
    job_status = SynthesisJobStatus(
        job_id=job_id,
        status=JobStatusEnum.PENDING,
        progress=0,
        detail="Initializing background task",
        created_at=now,
        updated_at=now
    )
    job_store[job_id] = job_status

    async def progress_callback(event: dict):
        job = job_store.get(job_id)
        if job:
            job.status = JobStatusEnum.PROCESSING
            job.progress = event.get("progress", job.progress)
            job.detail = event.get("label", job.detail)
            job.updated_at = datetime.datetime.now().isoformat()

    async def run_task():
        try:
            result = await run_synthesis_pipeline(payload, username=current_user["username"], progress_callback=progress_callback)
            job = job_store.get(job_id)
            if job:
                job.status = JobStatusEnum.COMPLETED
                job.progress = 100
                job.detail = "Synthesis complete"
                job.result = result
                job.updated_at = datetime.datetime.now().isoformat()
        except Exception as exc:
            logger.exception("Background synthesis failed for job %s: %s", job_id, exc)
            job = job_store.get(job_id)
            if job:
                job.status = JobStatusEnum.FAILED
                job.error = str(exc)
                job.updated_at = datetime.datetime.now().isoformat()

    asyncio.create_task(run_task())
    return {"job_id": job_id, "status": "accepted"}

@router.get(
    "/status/{job_id}",
    response_model=SynthesisJobStatus,
    summary="Check status of a background synthesis job",
)
async def get_job_status(job_id: str):
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found"
        )
    return job



# BATCH GAP DETECTION
@router.post(
    "/gaps/batch",
    response_model=List[SynthesisResponse],
    status_code=status.HTTP_200_OK,
    summary="Analyze research gaps for multiple topics (max 5)",
)
async def detect_gaps_batch(
    payloads: List[SynthesisRequest],
    current_user: dict = Depends(require_researcher),
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
                continue
            output.append(result)

        return output

    except Exception as exc:
        logger.exception("Batch synthesis pipeline error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Batch synthesis failed: {exc}",
        )

# STREAM GAP DETECTION
@router.post(
    "/gaps/stream",
    status_code=status.HTTP_200_OK,
    summary="Analyze gaps with streamed progress",
)
async def stream_detect_gaps(
    payload: SynthesisRequest,
    current_user: dict = Depends(require_researcher),
) -> StreamingResponse:
    from app.services.synthesis.report_pipeline import run_synthesis_pipeline

    queue: asyncio.Queue[dict] = asyncio.Queue()

    async def progress_callback(event: dict) -> None:
        await queue.put({"type": "progress", **event})

    async def run_pipeline() -> None:
        try:
            result = await run_synthesis_pipeline(
                payload,
                username=current_user["username"],
                progress_callback=progress_callback
            )
            
            # Save search to history automatically
            filters = {
                "year": payload.year,
                "venue": payload.venue,
                "strict_venue": payload.strict_venue,
                "max_results": payload.max_results,
                "type": "synthesis"
            }
            await save_search_history(
                current_user["username"], 
                payload.topic, 
                filters, 
                result.papers_analyzed,
                report_id=result.report_id
            )
            await queue.put({"type": "result", "data": result.model_dump()})

        except Exception as exc:
            logger.exception("Synthesis stream error: %s", exc)
            await queue.put({"type": "error", "detail": str(exc)})

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

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson"
    )

@router.get(
    "/history",
    response_model=SynthesisHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="List past synthesis reports with cursor pagination",
)
async def get_synthesis_history(
    limit: int = 20,
    last_id: Optional[str] = None,
    current_user: dict = Depends(require_researcher),
) -> SynthesisHistoryResponse:
    collection = _get_gap_reports_collection()
    if collection is None:
        return SynthesisHistoryResponse(total=0, items=[])

    # Filter by user
    query = {"username": current_user["username"]}
    
    # Cursor pagination logic
    if last_id and _is_valid_object_id(last_id):
        query["_id"] = {"$lt": ObjectId(last_id)}

    total = await collection.count_documents({"username": current_user["username"]})
    
    cursor = collection.find(
        query, {"topic": 1, "papers_analyzed": 1, "gaps": 1, "created_at": 1}
    ).sort("_id", -1).limit(limit)
    
    items: list[SynthesisHistoryItem] = []
    async for doc in cursor:
        items.append(SynthesisHistoryItem(
            report_id=str(doc["_id"]),
            topic=doc.get("topic", ""),
            papers_analyzed=doc.get("papers_analyzed", 0),
            gap_count=len(doc.get("gaps", [])),
            created_at=doc.get("created_at", ""),
        ))
    
    next_cursor = str(items[-1].report_id) if items else None
    
    return SynthesisHistoryResponse(total=total, items=items, next_cursor=next_cursor)


@router.get(
    "/report/{report_id}",
    response_model=SynthesisResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve a saved synthesis report by ID",
)
async def get_synthesis_report(
    report_id: str,
    current_user: dict = Depends(require_researcher),
) -> SynthesisResponse:
    doc = _hydrate_report(await _fetch_report(report_id))
    return SynthesisResponse(**doc)


@router.get(
    "/public/report/{report_id}",
    response_model=SynthesisResponse,
    status_code=status.HTTP_200_OK,
    summary="Publicly retrieve a saved report (share links)",
)
async def get_public_synthesis_report(
    report_id: str,
    current_user: dict = Depends(require_viewer)
) -> SynthesisResponse:
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
    current_user: dict = Depends(require_researcher),
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
