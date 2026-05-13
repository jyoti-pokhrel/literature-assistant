import os
from typing import List

import httpx
from httpx import HTTPStatusError

from app.schemas.paper import RetrievedPaper
from app.services.extraction.normalizer import _venue_terms, clean_text, filter_papers
from app.core.http import get_http_client
from app.services.retrieval.cache import semantic_scholar_cache

SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
SEMANTIC_SCHOLAR_FIELDS = ",".join(
    [
        "paperId",
        "title",
        "abstract",
        "authors",
        "year",
        "venue",
        "publicationVenue",
        "journal",
        "url",
        "citationCount",
        "openAccessPdf",
    ]
)

PAGE_SIZE = 100
MAX_CANDIDATES = 200
MAX_OFFSET = 1000  # API hard limit on offset+limit


def _extract_venue(item: dict) -> str | None:
    publication_venue = item.get("publicationVenue") or {}
    journal = item.get("journal") or {}
    return clean_text(
        item.get("venue")
        or publication_venue.get("name")
        or journal.get("name")
    )


def _parse_items(payload: dict) -> List[RetrievedPaper]:
    papers: List[RetrievedPaper] = []
    for item in payload.get("data", []):
        title = clean_text(item.get("title"))
        if not title:
            continue
        authors = [author.get("name", "").strip() for author in item.get("authors", []) if author.get("name")]
        pdf = item.get("openAccessPdf") or {}
        papers.append(
            RetrievedPaper(
                source="semantic_scholar",
                external_id=item.get("paperId"),
                title=title,
                abstract=clean_text(item.get("abstract")),
                authors=authors,
                year=item.get("year"),
                venue=_extract_venue(item),
                url=item.get("url"),
                pdf_url=pdf.get("url"),
                citation_count=item.get("citationCount"),
            )
        )
    return papers


async def _fetch_page(
    client: httpx.AsyncClient,
    *,
    topic: str,
    venue: str | None,
    year: str | int | None,
    offset: int,
    limit: int,
    headers: dict,
) -> List[RetrievedPaper]:
    # Cache key for individual page fetches
    cache_key = f"fetch_page:{topic}:{venue}:{year}:{offset}:{limit}"
    cached_results = await semantic_scholar_cache.get(cache_key)
    if cached_results is not None:
        return cached_results

    params: dict = {
        "query": topic,
        "offset": offset,
        "limit": limit,
        "fields": SEMANTIC_SCHOLAR_FIELDS,
    }
    if venue:
        venue_terms = _venue_terms(venue)
        if venue_terms:
            params["venue"] = ",".join(venue_terms)
    if year is not None:
        params["year"] = str(year)
    try:
        response = await client.get(SEMANTIC_SCHOLAR_URL, params=params, headers=headers)
        response.raise_for_status()
        results = _parse_items(response.json())
        await semantic_scholar_cache.set(cache_key, results)
        return results
    except (HTTPStatusError, httpx.RequestError):
        return []


async def search_semantic_scholar(
    topic: str,
    *,
    year: str | int | None = None,
    venue: str | None = None,
    strict_venue: bool = False,
    limit: int = 10,
    timeout: int = 20,
) -> List[RetrievedPaper]:
    headers: dict = {}
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key

    cleaned_topic = clean_text(topic) or topic
    cleaned_venue = clean_text(venue)
    filters_active = cleaned_venue is not None or year is not None

    candidates: List[RetrievedPaper] = []
    seen_ids: set[str] = set()
    offset = 0
    page_size = min(max(limit * 5, limit), 50) if not filters_active else PAGE_SIZE

    # High-level cache for the full search result
    full_cache_key = f"search:{topic}:{year}:{venue}:{strict_venue}:{limit}"
    cached_search = await semantic_scholar_cache.get(full_cache_key)
    if cached_search is not None:
        return cached_search

    client = get_http_client()
    while len(candidates) < MAX_CANDIDATES and offset < MAX_OFFSET:
        this_page = min(page_size, MAX_OFFSET - offset)
        page = await _fetch_page(
            client,
            topic=cleaned_topic,
            venue=cleaned_venue,
            year=year,
            offset=offset,
            limit=this_page,
            headers=headers,
        )
        if not page:
            break
        for paper in page:
            pid = paper.external_id or paper.url or paper.title
            if pid in seen_ids:
                continue
            seen_ids.add(pid)
            candidates.append(paper)

        filtered_so_far = filter_papers(
            candidates, year=year, venue=cleaned_venue, strict_venue=strict_venue
        )
        if len(filtered_so_far) >= limit or not filters_active:
            break
        offset += this_page

    final_results = filter_papers(
        candidates, year=year, venue=cleaned_venue, strict_venue=strict_venue
    )[:limit]
    
    await semantic_scholar_cache.set(full_cache_key, final_results)
    return final_results
