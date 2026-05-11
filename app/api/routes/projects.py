from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_current_user
from app.db.guards import require_collection
from app.db.session import projects_collection
from app.models.project import Project, ProjectUpdate

router = APIRouter(prefix="/projects", tags=["Projects"])


def _validate_object_id(id_str: str) -> ObjectId:
    if not ObjectId.is_valid(id_str):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"'{id_str}' is not a valid project id",
        )
    return ObjectId(id_str)


def _serialize(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    return doc


def _owner_key(current_user: dict) -> str:
    return current_user.get("username") or "local-test-user"


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_project(
    project: Project,
    current_user: dict = Depends(get_current_user),
):
    collection = require_collection(projects_collection, "project creation")
    payload = project.model_dump()
    payload["owner"] = _owner_key(current_user)
    inserted = await collection.insert_one(payload)
    payload["id"] = str(inserted.inserted_id)
    return payload


@router.get("", status_code=status.HTTP_200_OK)
async def list_projects(
    include_archived: bool = False,
    current_user: dict = Depends(get_current_user),
):
    collection = require_collection(projects_collection, "project listing")
    query: dict = {"owner": _owner_key(current_user)}
    if not include_archived:
        query["archived"] = {"$ne": True}

    items: list[dict] = []
    cursor = collection.find(query).sort("updated_at", -1)
    async for doc in cursor:
        items.append(_serialize(doc))
    return {"total": len(items), "items": items}


@router.get("/{project_id}", status_code=status.HTTP_200_OK)
async def get_project(
    project_id: str,
    current_user: dict = Depends(get_current_user),
):
    collection = require_collection(projects_collection, "project lookup")
    oid = _validate_object_id(project_id)
    doc = await collection.find_one({"_id": oid, "owner": _owner_key(current_user)})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found",
        )
    return _serialize(doc)


@router.patch("/{project_id}", status_code=status.HTTP_200_OK)
async def update_project(
    project_id: str,
    update: ProjectUpdate,
    current_user: dict = Depends(get_current_user),
):
    collection = require_collection(projects_collection, "project update")
    oid = _validate_object_id(project_id)

    changes = {k: v for k, v in update.model_dump(exclude_none=True).items()}
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )
    changes["updated_at"] = datetime.now(timezone.utc)

    result = await collection.update_one(
        {"_id": oid, "owner": _owner_key(current_user)},
        {"$set": changes},
    )
    if result.matched_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found",
        )

    doc = await collection.find_one({"_id": oid})
    return _serialize(doc)


@router.delete("/{project_id}", status_code=status.HTTP_200_OK)
async def archive_project(
    project_id: str,
    current_user: dict = Depends(get_current_user),
):
    collection = require_collection(projects_collection, "project archive")
    oid = _validate_object_id(project_id)
    result = await collection.update_one(
        {"_id": oid, "owner": _owner_key(current_user)},
        {"$set": {"archived": True, "updated_at": datetime.now(timezone.utc)}},
    )
    if result.matched_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found",
        )
    return {"message": "Project archived", "id": project_id}
