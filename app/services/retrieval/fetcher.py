import asyncio

from app.schemas.paper import PaperSearchResponse, RetrievedPaper
from app.services.extraction.normalizer import clean_text, deduplicate_papers
from app.services.retrieval.openalex_client import search_openalex
from app.services.retrieval.arxiv_client import search_arxiv
from app.services.retrieval.semantic_scholar_client import search_semantic_scholar
from app.services.retrieval.tavily_client import search_tavily

PRIMARY_SOURCES: tuple[str, str, str] = ("semantic_scholar", "openalex", "arxiv")
FALLBACK_SOURCE = "tavily"
PLACEHOLDER_FILTER_VALUES = {"string", "none", "null", "undefined", "all", "any"}


def _normalize_optional_filter(value: str | None) -> str | None:
    normalized = clean_text(value)
    if not normalized:
        return None
    if normalized.lower() in PLACEHOLDER_FILTER_VALUES:
        return None
    return normalized


async def retrieve_papers(
    topic: str,
    *,
    year: str | None = None,
    venue: str | None = None,
    max_results: int = 10,
) -> PaperSearchResponse:
    year = _normalize_optional_filter(year)
    venue = _normalize_optional_filter(venue)

    sources_used: list[str] = []
    merged: list[RetrievedPaper] = []

    # Run primary sources concurrently
    fetchers = [
        ("semantic_scholar", search_semantic_scholar),
        ("openalex", search_openalex),
tasks = [
    fetcher(topic, year=year, venue=venue, limit=max_results)
    for _, fetcher in fetchers
]

results_list = await asyncio.gather(*tasks, return_exceptions=True)

results_by_source = {}

for (source_name, _), results in zip(fetchers, results_list):
    if isinstance(results, Exception):
        logger.warning("Fetcher failed for %s: %s", source_name, results)
        results_by_source[source_name] = []
        continue

    results_by_source[source_name] = results
        if not results:
            continue
        sources_used.append(source_name)
        merged = deduplicate_papers([*merged, *results])

    if not merged:
        tavily_results = await search_tavily(
            topic,
            year=year,
            venue=venue,
            limit=max_results,
        )
        if tavily_results:
            sources_used.append(FALLBACK_SOURCE)
            merged = deduplicate_papers([*merged, *tavily_results])

    merged.sort(key=lambda paper: ((paper.citation_count or 0), (paper.year or 0)), reverse=True)
    papers = merged[:max_results]

    filters = {}
    if year is not None:
        filters["year"] = year
    if venue:
        filters["venue"] = venue

    return PaperSearchResponse(
        topic=topic,
        filters=filters,
        sources_used=sources_used,
        count=len(papers),
        papers=papers,
    )
