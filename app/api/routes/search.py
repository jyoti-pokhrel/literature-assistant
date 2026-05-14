from fastapi import APIRouter, Depends, HTTPException, status
import logging
from datetime import datetime, timezone

from app.api.dependencies import require_researcher
from app.db.session import get_db
from app.schemas.gap_analysis import GapAnalysisRequest, GapAnalysisResponse
from app.schemas.paper import (
    ArxivExploreRequest,
    ArxivExploreResponse,
    PaperSearchRequest,
    PaperSearchResponse,
)
from app.services.orchestration.pipeline import run_gap_analysis
from app.services.retrieval.arxiv_client import fetch_arxiv_page
from app.services.retrieval.fetcher import retrieve_papers
from app.services.retrieval.history import save_search_history


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/search/papers", response_model=PaperSearchResponse, status_code=status.HTTP_200_OK)
async def search_papers(
    payload: PaperSearchRequest,
    current_user: dict = Depends(require_researcher),
):
    results = await retrieve_papers(
        payload.topic,
        year=payload.year,
        venue=payload.venue,
        strict_venue=payload.strict_venue,
        max_results=payload.max_results,
    )
    
    # Save to history automatically
    filters = {
        "year": payload.year,
        "venue": payload.venue,
        "strict_venue": payload.strict_venue,
        "max_results": payload.max_results
    }
    await save_search_history(current_user["username"], payload.topic, filters, results.results_count if hasattr(results, "results_count") else 0)
    
    return results


@router.post("/analysis/gaps", response_model=GapAnalysisResponse, status_code=status.HTTP_200_OK)
async def analyze_gaps_for_topic(
    payload: GapAnalysisRequest,
    current_user: dict = Depends(require_researcher),
):
    result = await run_gap_analysis(
        topic=payload.topic,
        year=payload.year,
        venue=payload.venue,
        strict_venue=payload.strict_venue,
        max_results=payload.max_results,
        top_k_gaps=payload.top_k_gaps,
    )
    
    # Save to history
    filters = {
        "year": payload.year,
        "venue": payload.venue,
        "max_results": payload.max_results,
        "top_k_gaps": payload.top_k_gaps,
        "type": "gap_analysis"
    }
    await save_search_history(current_user["username"], payload.topic, filters)
    
    return result


@router.post(
    "/explore/arxiv",
    response_model=ArxivExploreResponse,
    status_code=status.HTTP_200_OK,
    summary="Browse similar arXiv papers with cursor pagination",
)
async def explore_arxiv(
    payload: ArxivExploreRequest,
    current_user: dict = Depends(require_researcher),
):
    papers, next_cursor, has_more = await fetch_arxiv_page(
        payload.topic,
        year=payload.year,
        venue=payload.venue,
        strict_venue=payload.strict_venue,
        cursor=payload.cursor,
        page_size=payload.page_size,
    )

    filters: dict = {}
    if payload.year:
        filters["year"] = payload.year
    if payload.venue:
        filters["venue"] = payload.venue
        filters["strict_venue"] = payload.strict_venue

    return ArxivExploreResponse(
        topic=payload.topic,
        filters=filters,
        papers=papers,
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.get("/search/history", summary="Retrieve search history for current user")
async def get_search_history(current_user: dict = Depends(require_researcher)):
    try:
        db = get_db()
        cursor = db.search_history.find({"username": current_user["username"]}).sort("created_at", -1).limit(50)
        history = await cursor.to_list(length=50)
        for doc in history:
            doc["id"] = str(doc["_id"])
            del doc["_id"]
        return history
    except Exception as e:
        logger.error(f"Error fetching search history: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch history")

@router.delete("/search/history/{history_id}")
async def delete_search_history(history_id: str, current_user: dict = Depends(require_researcher)):
    try:
        from bson import ObjectId
        db = get_db()
        result = await db.search_history.delete_one({
            "_id": ObjectId(history_id),
            "username": current_user["username"]
        })
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="History item not found")
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/search/history")
async def clear_search_history(current_user: dict = Depends(require_researcher)):
    try:
        db = get_db()
        result = await db.search_history.delete_many({"username": current_user["username"]})
        return {"success": True, "deleted_count": result.deleted_count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
