import asyncio
import logging
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_current_user
from app.db.guards import require_collection
from app.db.session import gap_feedback_signals_collection, gap_reports_collection
from app.models.gap_feedback import GapFeedbackPatch
from app.services.recommendations import profile_builder

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/synthesis/report", tags=["Feedback"])


def _gap_title(gap: dict) -> str:
    for key in ("title", "gap_title", "summary"):
        value = gap.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _gap_description(gap: dict) -> str:
    for key in ("description", "details", "explanation", "summary"):
        value = gap.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


async def _log_feedback_signal(
    username: str,
    report_id: str,
    gap_id: str,
    gap: dict,
    feedback: dict,
) -> None:
    if gap_feedback_signals_collection is None or not username:
        return
    try:
        await gap_feedback_signals_collection.update_one(
            {"username": username, "report_id": report_id, "gap_id": gap_id},
            {
                "$set": {
                    "username": username,
                    "report_id": report_id,
                    "gap_id": gap_id,
                    "gap_title": _gap_title(gap),
                    "gap_description": _gap_description(gap),
                    "vote": feedback.get("vote"),
                    "pursue": bool(feedback.get("pursue")),
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )
    except Exception:
        logger.exception("Failed to log gap feedback signal for %s", username)


def _is_valid_object_id(s: str) -> bool:
    return ObjectId.is_valid(s)


async def _fetch_report_doc(report_id: str) -> dict:
    coll = require_collection(gap_reports_collection, "feedback")
    clean = report_id.strip()
    query: dict = {"$or": [{"report_id": clean}]}
    if _is_valid_object_id(clean):
        query["$or"].append({"_id": ObjectId(clean)})
    doc = await coll.find_one(query)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report '{report_id}' not found",
        )
    return doc


@router.post(
    "/{report_id}/gaps/{gap_id}/feedback",
    status_code=status.HTTP_200_OK,
    summary="Record researcher feedback on a single gap",
)
async def upsert_gap_feedback(
    report_id: str,
    gap_id: str,
    patch: GapFeedbackPatch,
    current_user: dict = Depends(get_current_user),
):
    coll = require_collection(gap_reports_collection, "feedback")
    doc = await _fetch_report_doc(report_id)

    gaps = doc.get("gaps") or []
    target_idx = next(
        (i for i, g in enumerate(gaps) if str(g.get("gap_id")) == gap_id),
        None,
    )
    if target_idx is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Gap '{gap_id}' not found in report '{report_id}'",
        )

    existing = gaps[target_idx].get("feedback") or {
        "vote": None,
        "addressed_by": None,
        "pursue": False,
        "note": "",
    }

    if patch.clear_vote:
        existing["vote"] = None
    elif patch.vote is not None:
        existing["vote"] = patch.vote

    if patch.clear_addressed_by:
        existing["addressed_by"] = None
    elif patch.addressed_by is not None:
        existing["addressed_by"] = patch.addressed_by

    if patch.pursue is not None:
        existing["pursue"] = bool(patch.pursue)

    if patch.note is not None:
        existing["note"] = patch.note

    existing["updated_at"] = datetime.now(timezone.utc)

    update_path = f"gaps.{target_idx}.feedback"
    await coll.update_one({"_id": doc["_id"]}, {"$set": {update_path: existing}})

    username = current_user.get("username") or "local-test-user"
    await _log_feedback_signal(username, str(doc["_id"]), gap_id, gaps[target_idx], existing)
    asyncio.create_task(profile_builder.invalidate(username))

    return {"gap_id": gap_id, "feedback": existing}


@router.get(
    "/{report_id}/gaps/{gap_id}/feedback",
    status_code=status.HTTP_200_OK,
)
async def get_gap_feedback(
    report_id: str,
    gap_id: str,
    current_user: dict = Depends(get_current_user),
):
    doc = await _fetch_report_doc(report_id)
    gaps = doc.get("gaps") or []
    for g in gaps:
        if str(g.get("gap_id")) == gap_id:
            return {"gap_id": gap_id, "feedback": g.get("feedback")}
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Gap '{gap_id}' not found in report '{report_id}'",
    )
