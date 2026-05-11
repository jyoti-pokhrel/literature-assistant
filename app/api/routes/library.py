from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_current_user
from app.db.guards import require_collection
from app.db.session import library_items_collection, projects_collection
from app.models.library_item import (
    LibraryItemCreate,
    LibraryItemUpdate,
    paper_key,
)

router = APIRouter(prefix="/projects/{project_id}/library", tags=["Library"])


def _owner_key(current_user: dict) -> str:
    return current_user.get("username") or "local-test-user"


def _validate_object_id(id_str: str, label: str) -> ObjectId:
    if not ObjectId.is_valid(id_str):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"'{id_str}' is not a valid {label}",
        )
    return ObjectId(id_str)


async def _ensure_project(project_id: str, owner: str) -> ObjectId:
    coll = require_collection(projects_collection, "project lookup")
    oid = _validate_object_id(project_id, "project id")
    doc = await coll.find_one({"_id": oid, "owner": owner})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found",
        )
    return oid


def _serialize(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    doc["paper_key"] = paper_key(doc["source"], doc.get("external_id"))
    return doc


@router.post("", status_code=status.HTTP_201_CREATED)
async def save_to_library(
    project_id: str,
    payload: LibraryItemCreate,
    current_user: dict = Depends(get_current_user),
):
    owner = _owner_key(current_user)
    await _ensure_project(project_id, owner)

    if not payload.paper.external_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Paper external_id is required to save to library",
        )

    coll = require_collection(library_items_collection, "library save")
    now = datetime.now(timezone.utc)
    paper_doc = payload.paper.model_dump()

    filter_q = {
        "project_id": project_id,
        "owner": owner,
        "source": payload.paper.source,
        "external_id": payload.paper.external_id,
    }
    update = {
        "$set": {
            "paper": paper_doc,
            "notes": payload.notes or "",
            "status": payload.status,
            "tags": payload.tags or [],
            "updated_at": now,
        },
        "$setOnInsert": {
            "created_at": now,
            **filter_q,
        },
    }
    await coll.update_one(filter_q, update, upsert=True)
    saved = await coll.find_one(filter_q)
    return _serialize(saved)


@router.get("", status_code=status.HTTP_200_OK)
async def list_library(
    project_id: str,
    status_filter: str | None = None,
    tag: str | None = None,
    current_user: dict = Depends(get_current_user),
):
    owner = _owner_key(current_user)
    await _ensure_project(project_id, owner)

    coll = require_collection(library_items_collection, "library listing")
    query: dict = {"project_id": project_id, "owner": owner}
    if status_filter:
        query["status"] = status_filter
    if tag:
        query["tags"] = tag

    items: list[dict] = []
    cursor = coll.find(query).sort("updated_at", -1)
    async for doc in cursor:
        items.append(_serialize(doc))
    return {"total": len(items), "items": items}


@router.patch("/{paper_key_value}", status_code=status.HTTP_200_OK)
async def update_library_item(
    project_id: str,
    paper_key_value: str,
    update: LibraryItemUpdate,
    current_user: dict = Depends(get_current_user),
):
    owner = _owner_key(current_user)
    await _ensure_project(project_id, owner)

    if ":" not in paper_key_value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="paper_key must be in the form 'source:external_id'",
        )
    source, external_id = paper_key_value.split(":", 1)

    changes = {k: v for k, v in update.model_dump(exclude_none=True).items()}
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )
    changes["updated_at"] = datetime.now(timezone.utc)

    coll = require_collection(library_items_collection, "library update")
    filter_q = {
        "project_id": project_id,
        "owner": owner,
        "source": source,
        "external_id": external_id,
    }
    result = await coll.update_one(filter_q, {"$set": changes})
    if result.matched_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Library item '{paper_key_value}' not found",
        )
    doc = await coll.find_one(filter_q)
    return _serialize(doc)


@router.delete("/{paper_key_value}", status_code=status.HTTP_200_OK)
async def remove_from_library(
    project_id: str,
    paper_key_value: str,
    current_user: dict = Depends(get_current_user),
):
    owner = _owner_key(current_user)
    await _ensure_project(project_id, owner)

    if ":" not in paper_key_value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="paper_key must be in the form 'source:external_id'",
        )
    source, external_id = paper_key_value.split(":", 1)

    coll = require_collection(library_items_collection, "library delete")
    result = await coll.delete_one(
        {
            "project_id": project_id,
            "owner": owner,
            "source": source,
            "external_id": external_id,
        }
    )
    if result.deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Library item '{paper_key_value}' not found",
        )
    return {"message": "Removed from library", "paper_key": paper_key_value}
