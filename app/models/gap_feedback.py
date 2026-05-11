from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

Vote = Literal["up", "down"]


class GapFeedback(BaseModel):
    """Researcher feedback on a single detected gap.

    Persisted as a sub-document on the gap inside its gap_reports doc.
    Feeds back into future synthesis prompts to bias toward 'pursue this' themes
    and away from rejected categories.
    """

    vote: Optional[Vote] = None
    addressed_by: Optional[str] = None  # paper_key like "arxiv:2401.12345"
    pursue: bool = False
    note: str = ""
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("note")
    @classmethod
    def cap_note(cls, v):
        v = (v or "").strip()
        if len(v) > 280:
            raise ValueError("Note capped at 280 characters")
        return v


class GapFeedbackPatch(BaseModel):
    """Partial update — only fields explicitly set are applied."""

    vote: Optional[Vote] = None
    clear_vote: bool = False
    addressed_by: Optional[str] = None
    clear_addressed_by: bool = False
    pursue: Optional[bool] = None
    note: Optional[str] = None

    @field_validator("note")
    @classmethod
    def cap_note(cls, v):
        if v is None:
            return v
        v = v.strip()
        if len(v) > 280:
            raise ValueError("Note capped at 280 characters")
        return v
