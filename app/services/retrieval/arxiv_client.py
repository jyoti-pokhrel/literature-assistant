import xml.etree.ElementTree as ET
from typing import List

import httpx
from httpx import HTTPStatusError

from app.schemas.paper import RetrievedPaper
from app.services.extraction.normalizer import VENUE_ALIASES, clean_text, filter_papers


ARXIV_URL = "https://export.arxiv.org/api/query"
ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}
PAGE_SIZE = 100  # arXiv allows large page sizes; 100 is a comfortable max.
MAX_CANDIDATES = 200


def _node_text(node, path: str) -> str | None:
    found = node.find(path, ATOM_NS)
    if found is None or found.text is None:
        return None
    return clean_text(found.text)


def _detect_venue(*texts: str | None) -> str | None:
    """Look for a known venue alias inside arXiv's journal_ref / comment text."""
    haystack = " ".join(t for t in texts if t).lower()
    if not haystack:
        return None
    for canonical, aliases in VENUE_ALIASES.items():
        for alias in aliases:
            if alias in haystack:
                return canonical.upper() if len(canonical) <= 6 else canonical.title()
    return None


def _parse_entries(root: ET.Element) -> List[RetrievedPaper]:
    papers: List[RetrievedPaper] = []
    for entry in root.findall("atom:entry", ATOM_NS):
        title = _node_text(entry, "atom:title")
        if not title:
            continue

        entry_id = _node_text(entry, "atom:id")
        published = _node_text(entry, "atom:published")
        paper_year = (
            int(published[:4])
            if published and len(published) >= 4 and published[:4].isdigit()
            else None
        )
        authors = [
            clean_text(author.findtext("atom:name", default="", namespaces=ATOM_NS))
            for author in entry.findall("atom:author", ATOM_NS)
        ]
        authors = [author for author in authors if author]

        pdf_url = None
        for link in entry.findall("atom:link", ATOM_NS):
            if link.attrib.get("title") == "pdf":
                pdf_url = link.attrib.get("href")
                break

        journal_ref = _node_text(entry, "arxiv:journal_ref")
        comment = _node_text(entry, "arxiv:comment")
        detected_venue = _detect_venue(journal_ref, comment)

        papers.append(
            RetrievedPaper(
                source="arxiv",
                external_id=entry_id.rsplit("/", 1)[-1] if entry_id else None,
                title=title,
                abstract=_node_text(entry, "atom:summary"),
                authors=authors,
                year=paper_year,
                venue=detected_venue or "arXiv",
                url=entry_id,
                pdf_url=pdf_url,
                citation_count=None,
            )
        )
    return papers


async def _fetch_page(
    client: httpx.AsyncClient,
    *,
    topic: str,
    start: int,
    page_size: int,
) -> List[RetrievedPaper]:
    cleaned_topic = (topic or "").strip()
    if cleaned_topic:
        params = {
            "search_query": f"all:{cleaned_topic}",
            "start": start,
            "max_results": page_size,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
    else:
        # No topic: feed-style browse over all of arXiv, newest first.
        # arXiv's API rejects `all:*` with a 500; `cat:*` matches every entry
        # across all categories and works as the "latest" feed.
        params = {
            "search_query": "cat:*",
            "start": start,
            "max_results": page_size,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
    try:
        response = await client.get(ARXIV_URL, params=params)
        response.raise_for_status()
        root = ET.fromstring(response.text)
    except (HTTPStatusError, httpx.RequestError, ET.ParseError):
        return []
    return _parse_entries(root)


async def search_arxiv(
    topic: str,
    *,
    year: int | str | None = None,
    venue: str | None = None,
    strict_venue: bool = False,
    limit: int = 10,
    timeout: int = 20,
) -> List[RetrievedPaper]:
    cleaned_venue = clean_text(venue)
    filters_active = cleaned_venue is not None or year is not None

    candidates: List[RetrievedPaper] = []
    seen_ids: set[str] = set()
    start = 0
    page_size = min(max(limit * 2, limit), 20) if not filters_active else PAGE_SIZE

    async with httpx.AsyncClient(timeout=timeout) as client:
        while len(candidates) < MAX_CANDIDATES:
            results = await _fetch_page(
                client, topic=topic, start=start, page_size=page_size
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
            start += page_size

    return filter_papers(
        candidates, year=year, venue=cleaned_venue, strict_venue=strict_venue
    )[:limit]


async def fetch_arxiv_page(
    topic: str | None = None,
    *,
    year: int | str | None = None,
    venue: str | None = None,
    strict_venue: bool = False,
    cursor: int = 0,
    page_size: int = 20,
    timeout: int = 20,
) -> tuple[List[RetrievedPaper], int, bool]:
    """Return one page of arXiv results for the Explore view.

    Walks arXiv starting at `cursor` in chunks of PAGE_SIZE, applies year/venue
    filtering, dedups by external_id, and stops once page_size filtered papers
    are collected or arXiv returns an empty chunk. The returned cursor is the
    raw arXiv `start` to use for the next call; has_more is False only when an
    arXiv response came back empty (i.e. end of the index for this query).
    """
    cleaned_venue = clean_text(venue)
    cursor = max(0, int(cursor))
    page_size = max(1, min(int(page_size), 50))

    collected: List[RetrievedPaper] = []
    seen_ids: set[str] = set()
    next_cursor = cursor
    has_more = True
    walked = 0

    topic_value = topic or ""

    async with httpx.AsyncClient(timeout=timeout) as client:
        while len(collected) < page_size and walked < MAX_CANDIDATES:
            chunk_size = min(PAGE_SIZE, MAX_CANDIDATES - walked)
            results = await _fetch_page(
                client, topic=topic_value, start=next_cursor, page_size=chunk_size
            )
            if not results:
                has_more = False
                break

            walked += len(results)
            next_cursor += len(results)

            filtered = filter_papers(
                results, year=year, venue=cleaned_venue, strict_venue=strict_venue
            )
            for paper in filtered:
                pid = paper.external_id or paper.url or paper.title
                if pid in seen_ids:
                    continue
                seen_ids.add(pid)
                collected.append(paper)
                if len(collected) >= page_size:
                    break

            # If arXiv returned fewer than we asked for, the index is exhausted.
            if len(results) < chunk_size:
                has_more = False
                break

    return collected[:page_size], next_cursor, has_more
