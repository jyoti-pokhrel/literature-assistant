from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_validator


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Project(BaseModel):
    name: str
    description: Optional[str] = None
    archived: bool = False
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    @field_validator("name")
    @classmethod
    def name_valid(cls, v: str) -> str:
        v = (v or "").strip()
        if len(v) < 1:
            raise ValueError("Project name must not be empty")
        if len(v) > 120:
            raise ValueError("Project name must be 120 characters or fewer")
        return v


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    archived: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def name_valid(cls, v):
        if v is None:
            return v
        v = v.strip()
        if len(v) < 1:
            raise ValueError("Project name must not be empty")
        if len(v) > 120:
            raise ValueError("Project name must be 120 characters or fewer")
        return v
