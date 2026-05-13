from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_current_user
from app.schemas.gap_analysis import GapAnalysisRequest, GapAnalysisResponse
from app.schemas.paper import (
    ArxivExploreRequest,
    ArxivExploreResponse,
    PaperSearchRequest,
    PaperSearchResponse,
)
from app.services.orchestration.pipeline import run_gap_analysis
from app.services.retrieval.arxiv_client import fetch_arxiv_page
from app.services.retrieval.fetcher import retrieve_papers


router = APIRouter()


@router.post("/search/papers", response_model=PaperSearchResponse, status_code=status.HTTP_200_OK)
async def search_papers(
    payload: PaperSearchRequest,
    current_user: dict = Depends(get_current_user),
):
    return await retrieve_papers(
        payload.topic,
        year=payload.year,
        venue=payload.venue,
        strict_venue=payload.strict_venue,
        max_results=payload.max_results,
    )


@router.post("/analysis/gaps", response_model=GapAnalysisResponse, status_code=status.HTTP_200_OK)
async def analyze_gaps_for_topic(
    payload: GapAnalysisRequest,
    current_user: dict = Depends(get_current_user),
):
    return await run_gap_analysis(
        topic=payload.topic,
        year=payload.year,
        venue=payload.venue,
        strict_venue=payload.strict_venue,
        max_results=payload.max_results,
        top_k_gaps=payload.top_k_gaps,
    )


@router.post(
    "/explore/arxiv",
    response_model=ArxivExploreResponse,
    status_code=status.HTTP_200_OK,
    summary="Browse similar arXiv papers with cursor pagination",
)
async def explore_arxiv(
    payload: ArxivExploreRequest,
    current_user: dict = Depends(get_current_user),
):
    papers, next_cursor, has_more = await fetch_arxiv_page(
        payload.topic,
        year=payload.year,
        venue=payload.venue,
        strict_venue=payload.strict_venue,
        cursor=payload.cursor,
        page_size=payload.page_size,
    )

    filters: dict = {}
    if payload.year:
        filters["year"] = payload.year
    if payload.venue:
        filters["venue"] = payload.venue
        filters["strict_venue"] = payload.strict_venue

    return ArxivExploreResponse(
        topic=payload.topic,
        filters=filters,
        papers=papers,
        next_cursor=next_cursor,
        has_more=has_more,
    )
