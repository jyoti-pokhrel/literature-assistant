from __future__ import annotations

import asyncio
import logging
import json
import os
from pathlib import Path
from typing import Dict, List

from bson import ObjectId
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response, StreamingResponse

from app.api.dependencies import get_current_user
from app.db.session import gap_reports_collection, cached_searches_collection
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

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent.parent.parent / ".env")

logger = logging.getLogger(__name__)

# Global job store for tracking background tasks
# In production, this could be moved to Redis or MongoDB TTL collection
job_store: Dict[str, SynthesisJobStatus] = {}

router = APIRouter(prefix="/synthesis", tags=["Synthesis"])


def _generate_search_hash(request: SynthesisRequest) -> str:
    import hashlib
    params = {
        "topic": request.topic.strip().lower(),
        "year": request.year or "",
        "venue": request.venue.strip().lower() if request.venue else "",
        "strict": request.strict_venue,
        "max_results": request.max_results,
        "top_k_gaps": request.top_k_gaps
    }
    param_str = json.dumps(params, sort_keys=True)
    return hashlib.md5(param_str.encode()).hexdigest()


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
    summary="Analyze research gaps for a single topic (Synchronous)",
)
async def detect_gaps(
    payload: SynthesisRequest,
    current_user: dict = Depends(get_current_user),
) -> SynthesisResponse:
    from app.services.synthesis.report_pipeline import run_synthesis_pipeline
    import datetime
    
    search_hash = _generate_search_hash(payload)

    if not payload.regenerate and cached_searches_collection is not None:
        cached_report = await cached_searches_collection.find_one({"search_hash": search_hash})
        if cached_report and "data" in cached_report:
            logger.info("Serving synthesis report from cache for hash: %s", search_hash)
            cached_data = cached_report["data"]
            # Enforce schema validation and inject cache meta
            response = SynthesisResponse(**cached_data)
            response.is_cached = True
            response.generated_at = cached_report.get("created_at", datetime.datetime.utcnow().isoformat())
            return response

    try:
        result = await run_synthesis_pipeline(payload, username=current_user["username"])
        
        # Save to cache asynchronously if DB is configured
        if cached_searches_collection is not None:
            # Dump to JSON first to ensure all dictionary keys (like ints) become strings for MongoDB
            result_dict = json.loads(result.model_dump_json())
            
            async def _save_cache():
                try:
                    await cached_searches_collection.update_one(
                        {"search_hash": search_hash},
                        {"$set": {
                            "data": result_dict,
                            "created_at": datetime.datetime.utcnow().isoformat()
                        }},
                        upsert=True
                    )
                except Exception as e:
                    logger.error("Failed to cache search: %s", e)
                    
            asyncio.create_task(_save_cache())
            
        return result
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
    current_user: dict = Depends(get_current_user),
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
    current_user: dict = Depends(get_current_user),
) -> StreamingResponse:
    from app.services.synthesis.report_pipeline import run_synthesis_pipeline

    queue: asyncio.Queue[dict] = asyncio.Queue()

    async def progress_callback(event: dict) -> None:
        await queue.put({"type": "progress", **event})

    async def run_pipeline() -> None:
        import datetime
        search_hash = _generate_search_hash(payload)
        
        try:
            # 1. Check cache first
            if not payload.regenerate and cached_searches_collection is not None:
                cached_report = await cached_searches_collection.find_one({"search_hash": search_hash})
                if cached_report and "data" in cached_report:
                    logger.info("Serving streaming synthesis from cache for hash: %s", search_hash)
                    cached_data = cached_report["data"]
                    cached_data["is_cached"] = True
                    cached_data["generated_at"] = cached_report.get("created_at", datetime.datetime.utcnow().isoformat())
                    await queue.put({"type": "result", "data": cached_data})
                    return

            # 2. Run normal pipeline if no cache
            result = await run_synthesis_pipeline(
                payload,
                username=current_user["username"],
                progress_callback=progress_callback
            )
            
            # 3. Save search to history automatically
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

            # 4. Save to cache asynchronously
            if cached_searches_collection is not None:
                result_dict = json.loads(result.model_dump_json())
                
                async def _save_cache_stream():
                    try:
                        await cached_searches_collection.update_one(
                            {"search_hash": search_hash},
                            {"$set": {
                                "data": result_dict,
                                "created_at": datetime.datetime.utcnow().isoformat()
                            }},
                            upsert=True
                        )
                    except Exception as e:
                        logger.error("Failed to cache stream search: %s", e)
                        
                asyncio.create_task(_save_cache_stream())

            await queue.put({"type": "result", "data": json.loads(result.model_dump_json())})

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
    doc = _hydrate_report(await _fetch_report(report_id))

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



@router.get(
    "/report/{report_id}/markdown",
    status_code=status.HTTP_200_OK,
    summary="Download synthesis report as Markdown",
    response_class=Response,
)
async def download_synthesis_report_markdown(
    report_id: str,
    current_user: dict = Depends(get_current_user),
):
    doc = _hydrate_report(await _fetch_report(report_id))
    md_content = doc.get("copy_text") or f"# Synthesis Report\n\nNo content available for report {report_id}."
    
    safe_topic = (doc.get("topic") or "report").replace(" ", "_")[:40]
    filename = f"synthesis_{safe_topic}_{report_id[:8]}.md"

    return Response(
        content=md_content.encode("utf-8"),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
