import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_current_user
from app.db.session import get_db, search_history_collection
from app.schemas.gap_analysis import GapAnalysisRequest, GapAnalysisResponse
from app.schemas.paper import (
    PaperSearchRequest,
    PaperSearchResponse,
)
from app.services.orchestration.pipeline import run_gap_analysis
from app.services.recommendations import profile_builder
from app.services.retrieval.fetcher import retrieve_papers
from app.services.retrieval.history import save_search_history

logger = logging.getLogger(__name__)
router = APIRouter()


def _username(current_user: dict) -> str:
    return current_user.get("username") or "local-test-user"


async def _record_search(
    username: str,
    payload: PaperSearchRequest,
    result: PaperSearchResponse,
) -> None:
    if search_history_collection is None or not username:
        return
    try:
        await search_history_collection.insert_one(
            {
                "username": username,
                "topic": payload.topic,
                "year": payload.year,
                "venue": payload.venue,
                "strict_venue": payload.strict_venue,
                "max_results": payload.max_results,
                "result_count": result.count,
                "created_at": datetime.now(timezone.utc),
            }
        )
    except Exception:
        logger.exception("Failed to persist search_history for %s", username)


@router.post("/search/papers", response_model=PaperSearchResponse, status_code=status.HTTP_200_OK)
async def search_papers(
    payload: PaperSearchRequest,
    current_user: dict = Depends(get_current_user),
):
    result = await retrieve_papers(
        payload.topic,
        year=payload.year,
        venue=payload.venue,
        strict_venue=payload.strict_venue,
        max_results=payload.max_results,
    )
    username = _username(current_user)
    await _record_search(username, payload, result)
    asyncio.create_task(profile_builder.invalidate(username))
    return result


@router.post("/analysis/gaps", response_model=GapAnalysisResponse, status_code=status.HTTP_200_OK)
async def analyze_gaps_for_topic(
    payload: GapAnalysisRequest,
    current_user: dict = Depends(get_current_user),
):
    result = await run_gap_analysis(
        topic=payload.topic,
        year=payload.year,
        venue=payload.venue,
        strict_venue=payload.strict_venue,
        max_results=payload.max_results,
        top_k_gaps=payload.top_k_gaps,
    )
    username = _username(current_user)
    if search_history_collection is not None and username:
        try:
            await search_history_collection.insert_one(
                {
                    "username": username,
                    "topic": payload.topic,
                    "year": payload.year,
                    "venue": payload.venue,
                    "strict_venue": payload.strict_venue,
                    "max_results": payload.max_results,
                    "result_count": getattr(result, "papers_analyzed", None),
                    "created_at": datetime.now(timezone.utc),
                    "source": "gap_analysis",
                }
            )
        except Exception:
            logger.exception("Failed to persist gap-analysis history for %s", username)
    asyncio.create_task(profile_builder.invalidate(username))
    return result


# ── Search History CRUD ──────────────────────────────────────────────────

@router.get("/search/history", summary="Retrieve search history for current user")
async def get_search_history(current_user: dict = Depends(get_current_user)):
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
async def delete_search_history(history_id: str, current_user: dict = Depends(get_current_user)):
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
async def clear_search_history(current_user: dict = Depends(get_current_user)):
    try:
        db = get_db()
        result = await db.search_history.delete_many({"username": current_user["username"]})
        return {"success": True, "deleted_count": result.deleted_count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
