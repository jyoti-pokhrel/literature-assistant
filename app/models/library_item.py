from datetime import datetime, timezone
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.paper import RetrievedPaper


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


LibraryStatus = Literal["to_read", "reading", "done"]


class LibraryItemCreate(BaseModel):
    paper: RetrievedPaper
    notes: Optional[str] = None
    status: LibraryStatus = "to_read"
    tags: List[str] = Field(default_factory=list)


class LibraryItemUpdate(BaseModel):
    notes: Optional[str] = None
    status: Optional[LibraryStatus] = None
    tags: Optional[List[str]] = None

    @field_validator("notes")
    @classmethod
    def cap_notes(cls, v):
        if v is None:
            return v
        v = v.strip()
        if len(v) > 4000:
            raise ValueError("Notes capped at 4000 characters")
        return v


class LibraryItem(BaseModel):
    project_id: str
    owner: str
    source: str
    external_id: str
    paper: dict
    notes: str = ""
    status: LibraryStatus = "to_read"
    tags: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


def paper_key(source: str, external_id: Optional[str]) -> str:
    """Stable key for a paper across sources. external_id can be missing for some sources."""
    eid = (external_id or "").strip()
    if not eid:
        raise ValueError("Paper external_id is required to add to library")
    return f"{source}:{eid}"
