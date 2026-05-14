import os
from typing import List

import httpx
from dotenv import load_dotenv
from httpx import HTTPStatusError

from app.schemas.paper import RetrievedPaper
from app.services.extraction.normalizer import clean_text, filter_papers
from app.core.http import get_http_client
from app.services.retrieval.cache import openalex_cache


load_dotenv()

OPENALEX_URL = "https://api.openalex.org/works"
PAGE_SIZE = 100  # OpenAlex allows up to 200 per page
MAX_CANDIDATES = 200


def _build_filter(year: int | str | None, venue: str | None) -> str | None:
    filters: list[str] = []
    if year is not None:
        year_value = str(year)
        if "-" in year_value:
            start, end = year_value.split("-", 1)
            filters.append(f"from_publication_date:{start}-01-01")
            filters.append(f"to_publication_date:{end}-12-31")
        else:
            filters.append(f"publication_year:{year_value}")
    if venue:
        # Push venue match down to OpenAlex; use the search-on-display-name filter.
        # Commas/colons in the value would break the filter syntax, so strip them.
        safe_venue = venue.replace(",", " ").replace(":", " ").strip()
        if safe_venue:
            filters.append(f"primary_location.source.display_name.search:{safe_venue}")
    return ",".join(filters) or None


def _parse_items(payload: dict) -> List[RetrievedPaper]:
    papers: List[RetrievedPaper] = []
    for item in payload.get("results", []):
        title = clean_text(item.get("display_name"))
        if not title:
            continue

        authors = []
        for authorship in item.get("authorships", []):
            author_name = clean_text((authorship.get("author") or {}).get("display_name"))
            if author_name:
                authors.append(author_name)

        primary_location = item.get("primary_location") or {}
        source = primary_location.get("source") or {}
        pdf_url = primary_location.get("pdf_url")
        landing_url = primary_location.get("landing_page_url") or item.get("doi")

        papers.append(
            RetrievedPaper(
                source="openalex",
                external_id=item.get("id"),
                title=title,
                abstract=clean_text(
                    item.get("abstract_inverted_index")
                    and _invert_abstract(item.get("abstract_inverted_index"))
                ),
                authors=authors,
                year=item.get("publication_year"),
                venue=clean_text(source.get("display_name")),
                url=landing_url,
                pdf_url=pdf_url,
                citation_count=item.get("cited_by_count"),
            )
        )
    return papers


async def _fetch_page(
    client: httpx.AsyncClient,
    *,
    topic: str,
    venue: str | None,
    year: int | str | None,
    page: int,
    per_page: int,
    headers: dict,
) -> List[RetrievedPaper]:
    # Cache key for individual page fetches
    cache_key = f"fetch_page:{topic}:{venue}:{year}:{page}:{per_page}"
    cached_results = await openalex_cache.get(cache_key)
    if cached_results is not None:
        return cached_results

    params: dict = {
        "search": topic,
        "per-page": per_page,
        "page": page,
    }
    filter_value = _build_filter(year=year, venue=venue)
    if filter_value:
        params["filter"] = filter_value
    try:
        response = await client.get(OPENALEX_URL, params=params, headers=headers)
        response.raise_for_status()
        results = _parse_items(response.json())
        await openalex_cache.set(cache_key, results)
        return results
    except (HTTPStatusError, httpx.RequestError):
        return []


async def search_openalex(
    topic: str,
    *,
    year: int | str | None = None,
    venue: str | None = None,
    strict_venue: bool = False,
    limit: int = 10,
    timeout: int = 20,
) -> List[RetrievedPaper]:
    api_key = os.getenv("OPENALEX_API_KEY")
    headers: dict = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    cleaned_topic = clean_text(topic) or topic
    cleaned_venue = clean_text(venue)
    filters_active = cleaned_venue is not None or year is not None

    per_page = min(max(limit * 5, limit), 50) if not filters_active else PAGE_SIZE
    candidates: List[RetrievedPaper] = []
    seen_ids: set[str] = set()
    page = 1

    # High-level cache for the full search result
    full_cache_key = f"search:{topic}:{year}:{venue}:{strict_venue}:{limit}"
    cached_search = await openalex_cache.get(full_cache_key)
    if cached_search is not None:
        return cached_search

    client = get_http_client()
    while len(candidates) < MAX_CANDIDATES:
        results = await _fetch_page(
            client,
            topic=cleaned_topic,
            venue=cleaned_venue,
            year=year,
            page=page,
            per_page=per_page,
            headers=headers,
        )
        if not results:
            break
        for paper in results:
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
        page += 1

    final_results = filter_papers(
        candidates, year=year, venue=cleaned_venue, strict_venue=strict_venue
    )[:limit]
    
    await openalex_cache.set(full_cache_key, final_results)
    return final_results


def _invert_abstract(inverted_index: dict | None) -> str | None:
    if not inverted_index:
        return None

    positions: dict[int, str] = {}
    for word, indexes in inverted_index.items():
        for index in indexes:
            if isinstance(index, int):
                positions[index] = word

    if not positions:
        return None

    return " ".join(positions[position] for position in sorted(positions))
