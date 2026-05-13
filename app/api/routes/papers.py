from fastapi import APIRouter, HTTPException, status, Depends
from bson import ObjectId
from app.models.paper import Paper
from app.api.dependencies import require_researcher 
from app.db.guards import require_collection
from app.db.session import get_db

router = APIRouter()

# Helper to validate MongoDB ID
def validate_object_id(id_str: str) -> ObjectId:
    if not ObjectId.is_valid(id_str):
        raise HTTPException(status_code=422, detail="Invalid ID format")
    return ObjectId(id_str)

@router.post("/papers", status_code=status.HTTP_201_CREATED)
async def create_paper(paper: Paper, current_user: dict = Depends(require_researcher)):
    db = get_db()
    collection = require_collection(db.papers if db else None, "paper creation")
    new_paper = await collection.insert_one(paper.model_dump())
    return {
        "message": f"Paper created by {current_user['username']}",
        "id": str(new_paper.inserted_id),
    }

@router.get("/papers", status_code=status.HTTP_200_OK)
async def get_papers(current_user: dict = Depends(require_researcher)):
    db = get_db()
    collection = require_collection(db.papers if db else None, "paper listing")
    papers = []
    async for p in collection.find():
        p["_id"] = str(p["_id"])
        papers.append(p)
    return papers