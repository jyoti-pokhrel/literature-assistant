from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from datetime import datetime, timezone
from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.schemas.user import ChatSave

router = APIRouter(prefix="/chat", tags=["chat"])

@router.post("/save")
async def save_chat(chat_data: ChatSave, current_user: dict = Depends(get_current_user)):
    try:
        db = get_db()
        chat_item = chat_data.dict()
        chat_item["username"] = current_user["username"]
        chat_item["created_at"] = datetime.now(timezone.utc)
        
        await db.chat_history.insert_one(chat_item)
        return {"success": True, "message": "Chat saved"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/history")
async def get_chat_history(current_user: dict = Depends(get_current_user)):
    try:
        db = get_db()
        cursor = db.chat_history.find({"username": current_user["username"]}).sort("created_at", -1).limit(50)
        history = await cursor.to_list(length=50)
        
        for item in history:
            item["_id"] = str(item["_id"])
            
        return history
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
