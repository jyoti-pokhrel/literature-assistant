from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from datetime import datetime, timezone
import logging
from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.schemas.history import ChatSessionCreate, ChatMessage
import uuid

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])

@router.post("/save")
async def save_chat_message(chat_data: ChatSessionCreate, current_user: dict = Depends(get_current_user)):
    """Automatically called after each chat interaction to save/update session history."""
    try:
        db = get_db()
        chat_item = chat_data.model_dump()
        chat_item["username"] = current_user["username"]
        now = datetime.now(timezone.utc)
        chat_item["created_at"] = now
        
        # Check if session already exists
        session = await db.chat_history.find_one({
            "session_id": chat_data.session_id,
            "user_id": str(current_user["_id"])
        })
        
        user_msg = ChatMessage(role="user", content=chat_data.message, timestamp=now)
        ai_msg = ChatMessage(role="assistant", content=chat_data.response, timestamp=now)
        
        if session:
            # Update existing session
            await db.chat_history.update_one(
                {"_id": session["_id"]},
                {
                    "$push": {"messages": {"$each": [user_msg.dict(), ai_msg.dict()]}},
                    "$set": {"updated_at": now}
                }
            )
            return {"success": True, "session_id": chat_data.session_id, "mode": "updated"}
        else:
            # Create new session
            new_session = {
                "user_id": str(current_user["_id"]),
                "username": current_user["username"],
                "session_id": chat_data.session_id or str(uuid.uuid4()),
                "title": chat_data.title or chat_data.message[:50] + "...",
                "messages": [user_msg.dict(), ai_msg.dict()],
                "created_at": now,
                "updated_at": now
            }
            await db.chat_history.insert_one(new_session)
            return {"success": True, "session_id": new_session["session_id"], "mode": "created"}
            
    except Exception as e:
        logger.error(f"Error saving chat history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/history")
async def get_chat_history(current_user: dict = Depends(get_current_user)):
    """Retrieve all chat sessions for the current user."""
    try:
        db = get_db()
        cursor = db.chat_history.find({"user_id": str(current_user["_id"])}).sort("updated_at", -1).limit(50)
        history = await cursor.to_list(length=50)
        
        for item in history:
            item["id"] = str(item["_id"])
            del item["_id"]
            
        return history
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/session/{session_id}")
async def delete_chat_session(session_id: str, current_user: dict = Depends(get_current_user)):
    """Delete a specific chat session."""
    try:
        db = get_db()
        result = await db.chat_history.delete_one({
            "session_id": session_id,
            "user_id": str(current_user["_id"])
        })
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"success": True, "message": "Session deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/clear")
async def clear_chat_history(current_user: dict = Depends(get_current_user)):
    """Delete all chat sessions for the current user."""
    try:
        db = get_db()
        result = await db.chat_history.delete_many({
            "user_id": str(current_user["_id"])
        })
        return {"success": True, "deleted_count": result.deleted_count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
