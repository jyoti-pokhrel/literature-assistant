from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict
from datetime import datetime

class SearchHistoryBase(BaseModel):
    topic: str
    filters: Optional[Dict[str, Any]] = None
    results_count: Optional[int] = 0

class SearchHistoryCreate(SearchHistoryBase):
    pass

class SearchHistory(SearchHistoryBase):
    id: str
    username: str
    created_at: datetime

    class Config:
        from_attributes = True

class ChatMessage(BaseModel):
    role: str # "user" or "assistant"
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class ChatSessionBase(BaseModel):
    session_id: str
    title: Optional[str] = "New Chat"

class ChatSessionCreate(ChatSessionBase):
    message: str # Initial message
    response: str # Initial response

class ChatSession(ChatSessionBase):
    id: str
    username: str
    messages: List[ChatMessage]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class HistoryResponse(BaseModel):
    searches: List[SearchHistory]
    chats: List[ChatSession]
