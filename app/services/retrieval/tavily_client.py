import os
import re
from typing import List

import httpx
from httpx import HTTPStatusError

from app.schemas.paper import RetrievedPaper
from app.services.extraction.normalizer import clean_text, filter_papers
from app.core.http import get_http_client
from app.services.retrieval.cache import tavily_cache


TAVILY_URL = "https://api.tavily.com/search"


def _extract_year(*values: str | None) -> int | None:
    for value in values:
        if not value:
            continue
        match = re.search(r"\b(19|20)\d{2}\b", value)
        if match:
            return int(match.group(0))
    return None


async def search_tavily(
    topic: str,
    *,
    year: int | str | None = None,
    venue: str | None = None,
    strict_venue: bool = False,
    limit: int = 10,
    timeout: int = 20,
) -> List[RetrievedPaper]:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return []

    # High-level cache for the full search result
    full_cache_key = f"search:{topic}:{year}:{venue}:{strict_venue}:{limit}"
    cached_search = await tavily_cache.get(full_cache_key)
    if cached_search is not None:
        return cached_search

    query_parts = [topic, "research paper"]
    if year is not None:
        query_parts.append(str(year))
    if venue:
        query_parts.append(venue)

    payload = {
        "query": " ".join(query_parts)
        + " site:arxiv.org OR site:semanticscholar.org OR site:acm.org OR site:ieeexplore.ieee.org OR site:openreview.net OR site:proceedings.mlr.press",
        "search_depth": "advanced",
        "max_results": min(max(limit * 2, limit), 10),
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        client = get_http_client()
        response = await client.post(TAVILY_URL, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
    except (HTTPStatusError, httpx.RequestError):
        return []

    papers: List[RetrievedPaper] = []
    for item in data.get("results", []):
        title = clean_text(item.get("title"))
        if not title:
            continue

        url = item.get("url")
        content = clean_text(item.get("content"))
        venue_value = clean_text(item.get("source"))
        paper_year = _extract_year(title, content, url)
        papers.append(
            RetrievedPaper(
                source="tavily",
                external_id=url,
                title=title,
                abstract=content,
                authors=[],
                year=paper_year,
                venue=venue_value,
                url=url,
                pdf_url=url if isinstance(url, str) and url.endswith(".pdf") else None,
                citation_count=None,
            )
        )

    final_results = filter_papers(papers, year=year, venue=venue, strict_venue=strict_venue)[:limit]
    await tavily_cache.set(full_cache_key, final_results)
    return final_results
