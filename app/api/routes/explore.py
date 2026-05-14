"""Personalized Explore feed endpoints.

Replaces the legacy `/explore/arxiv` keyword pagination with a ranked,
per-user stream backed by Atlas Vector Search.

Endpoints:
  * POST /explore/seed     — save 3 cold-start topics and build initial profile.
  * POST /explore/feed     — paginated recommendation feed.
  * GET  /explore/profile  — interpretable summary of the current profile.
"""

from __future__ import annotations

import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.api.dependencies import get_current_user
from app.services.recommendations import profile_builder
from app.services.recommendations.pipeline import (
    ColdStartRequired,
    DEFAULT_PAGE_SIZE,
    get_feed_page,
)

router = APIRouter(tags=["Explore"])


def _username(current_user: dict) -> str:
    return current_user.get("username") or "local-test-user"


def _personalization_enabled() -> bool:
    return os.environ.get("EXPLORE_USE_PERSONALIZED", "1") != "0"


class ExploreSeedRequest(BaseModel):
    topics: List[str] = Field(..., min_length=1, max_length=3)

    @field_validator("topics")
    @classmethod
    def validate_topics(cls, value: List[str]) -> List[str]:
        cleaned: list[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            stripped = item.strip()
            if len(stripped) < 3 or len(stripped) > 80:
                raise ValueError("each topic must be 3–80 characters")
            cleaned.append(stripped)
        if not cleaned:
            raise ValueError("at least one valid topic is required")
        return cleaned


class ExploreFeedRequest(BaseModel):
    cursor: int = Field(default=0, ge=0, le=10000)
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=50)


class ExplorePaper(BaseModel):
    source: Optional[str] = None
    external_id: Optional[str] = None
    title: Optional[str] = None
    abstract: Optional[str] = None
    authors: List[str] = Field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None
    url: Optional[str] = None
    pdf_url: Optional[str] = None
    citation_count: Optional[int] = None
    doi: Optional[str] = None
    reason: str = ""
    score: float = 0.0


class ExploreFeedResponse(BaseModel):
    papers: List[ExplorePaper]
    next_cursor: int
    has_more: bool
    profile_summary: dict


class ExploreSeedResponse(BaseModel):
    profile_summary: dict


class ExploreProfileResponse(BaseModel):
    profile_summary: dict
    is_cold_start: bool


def _ensure_enabled() -> None:
    if not _personalization_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "explore_disabled"},
        )


@router.post(
    "/explore/seed",
    response_model=ExploreSeedResponse,
    status_code=status.HTTP_200_OK,
    summary="Save cold-start topics and build the initial profile",
)
async def save_explore_seeds(
    payload: ExploreSeedRequest,
    current_user: dict = Depends(get_current_user),
):
    _ensure_enabled()
    profile = await profile_builder.set_seed_topics(_username(current_user), payload.topics)
    summary = {
        "top_topics": profile.top_topics,
        "seed_topics": profile.seed_topics,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
        "component_counts": _component_counts(profile.components),
        "is_cold_start": profile.is_cold_start,
    }
    return ExploreSeedResponse(profile_summary=summary)


@router.post(
    "/explore/feed",
    response_model=ExploreFeedResponse,
    status_code=status.HTTP_200_OK,
    summary="Personalized recommendation feed",
)
async def explore_feed(
    payload: ExploreFeedRequest,
    current_user: dict = Depends(get_current_user),
):
    _ensure_enabled()
    try:
        page = await get_feed_page(
            _username(current_user),
            cursor=payload.cursor,
            page_size=payload.page_size,
        )
    except ColdStartRequired:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "cold_start_required"},
        )
    return ExploreFeedResponse(
        papers=page.papers,
        next_cursor=page.next_cursor,
        has_more=page.has_more,
        profile_summary=page.profile_summary,
    )


@router.get(
    "/explore/profile",
    response_model=ExploreProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Interpretable summary of the user's recommendation profile",
)
async def explore_profile(current_user: dict = Depends(get_current_user)):
    _ensure_enabled()
    profile = await profile_builder.load_profile(_username(current_user))
    summary = {
        "top_topics": profile.top_topics,
        "seed_topics": profile.seed_topics,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
        "component_counts": _component_counts(profile.components),
    }
    return ExploreProfileResponse(
        profile_summary=summary,
        is_cold_start=profile.is_cold_start,
    )


def _component_counts(components) -> dict:
    counts: dict[str, int] = {}
    for component in components or []:
        kind = getattr(component, "kind", None) or (
            component.get("kind") if isinstance(component, dict) else None
        )
        if not kind:
            continue
        counts[kind] = counts.get(kind, 0) + 1
    return counts
