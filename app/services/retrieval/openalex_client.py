import os
from typing import List

import httpx
from dotenv import load_dotenv
from httpx import HTTPStatusError

from app.schemas.paper import RetrievedPaper
from app.services.extraction.normalizer import clean_text, filter_papers


load_dotenv()

OPENALEX_URL = "https://api.openalex.org/works"


def _build_filter(year: int | str | None = None) -> str | None:
    filters: list[str] = []
    if year is not None:
        year_value = str(year)
        if "-" in year_value:
            start, end = year_value.split("-", 1)
            filters.append(f"from_publication_date:{start}-01-01")
            filters.append(f"to_publication_date:{end}-12-31")
        else:
            filters.append(f"publication_year:{year_value}")
    return ",".join(filters) or None


def _query_with_venue(topic: str, venue: str | None) -> str:
    cleaned_topic = clean_text(topic) or topic
    cleaned_venue = clean_text(venue)
    if not cleaned_venue:
        return cleaned_topic
    return f"{cleaned_topic} {cleaned_venue}"


async def search_openalex(
    topic: str,
    *,
    year: int | None = None,
    venue: str | None = None,
    limit: int = 10,
    timeout: int = 20,
) -> List[RetrievedPaper]:
    api_key = os.getenv("OPENALEX_API_KEY")

    params = {
        "search": _query_with_venue(topic, venue),
        "per-page": min(max(limit * 5, limit), 50),
    }
    filter_value = _build_filter(year=year)
    if filter_value:
        params["filter"] = filter_value

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(OPENALEX_URL, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except (HTTPStatusError, httpx.RequestError):
        return []

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
                abstract=clean_text(item.get("abstract_inverted_index") and _invert_abstract(item.get("abstract_inverted_index"))),
                authors=authors,
                year=item.get("publication_year"),
                venue=clean_text(source.get("display_name")),
                url=landing_url,
                pdf_url=pdf_url,
                citation_count=item.get("cited_by_count"),
            )
        )

    return filter_papers(papers, year=year, venue=venue)[:limit]


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
