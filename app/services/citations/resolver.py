from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from typing import Optional

import httpx


logger = logging.getLogger(__name__)


SEMANTIC_SCHOLAR_BASE = "https://api.semanticscholar.org/graph/v1"
OPENALEX_BASE = "https://api.openalex.org"
ARXIV_API_URL = "https://export.arxiv.org/api/query"

DEFAULT_TIMEOUT = 10.0
RETRY_BACKOFF_SECONDS = 1.5


DOI_BARE = re.compile(r"^10\.\d{4,9}/[-._;()/:A-Z0-9]+$", re.IGNORECASE)
DOI_URL = re.compile(
    r"^https?://(?:dx\.)?doi\.org/(?P<doi>10\.\d{4,9}/[-._;()/:A-Z0-9]+)$",
    re.IGNORECASE,
)
ARXIV_URL = re.compile(
    r"^https?://arxiv\.org/(?:abs|pdf)/(?P<id>\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?$",
    re.IGNORECASE,
)
ARXIV_ID = re.compile(r"^\d{4}\.\d{4,5}(?:v\d+)?$")
S2_URL = re.compile(
    r"^https?://(?:www\.)?semanticscholar\.org/paper/(?:[^/]+/)?(?P<id>[a-f0-9]{40})$",
    re.IGNORECASE,
)
OPENALEX_ID = re.compile(r"^W\d{6,12}$")
OPENALEX_URL = re.compile(r"^https?://openalex\.org/(?P<id>W\d{6,12})$", re.IGNORECASE)


@dataclass(frozen=True)
class CanonicalRef:
    """Canonical handle for a paper across S2, OpenAlex, arXiv, and bare DOI."""

    source: str
    external_id: str
    paper_id: str
    doi: Optional[str] = None
    title: Optional[str] = None
    year: Optional[int] = None
    url: Optional[str] = None


def _strip(raw: str) -> str:
    s = (raw or "").strip()
    while s.endswith("/"):
        s = s[:-1]
    return s


def _s2_headers() -> dict:
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    return {"x-api-key": api_key} if api_key else {}


def _openalex_headers() -> dict:
    api_key = os.getenv("OPENALEX_API_KEY")
    headers: dict = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    mailto = os.getenv("OPENALEX_MAILTO")
    if mailto:
        headers["User-Agent"] = f"research-agent (mailto:{mailto})"
    return headers


async def _http_get_json(
    client: httpx.AsyncClient, url: str, *, headers: Optional[dict] = None
) -> Optional[dict]:
    for attempt in range(2):
        try:
            response = await client.get(url, headers=headers or {})
            if response.status_code == 200:
                return response.json()
            if response.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS)
                continue
            return None
        except (httpx.RequestError, ValueError):
            if attempt == 0:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS)
                continue
            return None
    return None


def _ref_from_s2(payload: dict, source: str) -> CanonicalRef:
    external_ids = payload.get("externalIds") or {}
    doi = external_ids.get("DOI") or external_ids.get("doi")
    paper_id = payload.get("paperId") or ""
    return CanonicalRef(
        source=source,
        external_id=paper_id,
        paper_id=paper_id,
        doi=(doi or None) and doi.lower(),
        title=payload.get("title"),
        year=payload.get("year"),
        url=payload.get("url"),
    )


def _ref_from_openalex(payload: dict) -> CanonicalRef:
    work_id = (payload.get("id") or "").rsplit("/", 1)[-1]
    doi = payload.get("doi")
    if isinstance(doi, str) and doi.startswith("https://doi.org/"):
        doi = doi.split("https://doi.org/", 1)[1]
    return CanonicalRef(
        source="openalex",
        external_id=work_id,
        paper_id=f"OA:{work_id}" if work_id else "",
        doi=(doi or None) and doi.lower(),
        title=payload.get("display_name") or payload.get("title"),
        year=payload.get("publication_year"),
        url=(payload.get("primary_location") or {}).get("landing_page_url"),
    )


async def _s2_lookup(client: httpx.AsyncClient, prefixed_id: str) -> Optional[dict]:
    url = f"{SEMANTIC_SCHOLAR_BASE}/paper/{prefixed_id}?fields=paperId,externalIds,title,year,url"
    return await _http_get_json(client, url, headers=_s2_headers())


async def _openalex_lookup(
    client: httpx.AsyncClient, work_id_or_doi: str
) -> Optional[dict]:
    url = f"{OPENALEX_BASE}/works/{work_id_or_doi}"
    return await _http_get_json(client, url, headers=_openalex_headers())


async def _arxiv_metadata(client: httpx.AsyncClient, arxiv_id: str) -> Optional[dict]:
    """Fetch title / DOI / year for an arXiv ID via the public Atom API.

    Returns {"title", "doi", "year"} on success, else None. Used as a fallback
    enrichment path when Semantic Scholar's arXiv lookup is rate-limited.
    """
    import xml.etree.ElementTree as ET

    try:
        response = await client.get(
            ARXIV_API_URL,
            params={"id_list": arxiv_id},
            headers={
                "User-Agent": "research-agent citation-network (mailto:research-agent@example.com)"
            },
        )
        if response.status_code != 200 or not response.content:
            return None
        root = ET.fromstring(response.content)
    except (httpx.RequestError, ET.ParseError):
        return None

    ns = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    entry = root.find("a:entry", ns)
    if entry is None:
        return None
    title_el = entry.find("a:title", ns)
    published_el = entry.find("a:published", ns)
    doi_el = entry.find("arxiv:doi", ns)

    title = (title_el.text or "").strip() if title_el is not None else None
    year: Optional[int] = None
    if published_el is not None and published_el.text:
        try:
            year = int(published_el.text[:4])
        except ValueError:
            year = None
    doi = (doi_el.text or "").strip().lower() if doi_el is not None else None
    if not title and not doi:
        return None
    return {"title": title, "doi": doi or None, "year": year}


async def resolve_input(
    raw: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> Optional[CanonicalRef]:
    """Resolve an arbitrary user-supplied paper identifier into a CanonicalRef.

    Accepts: bare DOI, doi.org URL, arXiv ID, arXiv URL, Semantic Scholar paper URL,
    OpenAlex work ID, OpenAlex URL. Returns None for anything unrecognized.
    """
    text = _strip(raw)
    if not text:
        return None

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)

    try:
        # 1) Semantic Scholar URL: hash is already canonical paperId
        m = S2_URL.match(text)
        if m:
            s2_id = m.group("id")
            payload = await _s2_lookup(client, s2_id)
            if payload:
                return _ref_from_s2(payload, source="semantic_scholar")
            return CanonicalRef(
                source="semantic_scholar",
                external_id=s2_id,
                paper_id=s2_id,
            )

        # 2) OpenAlex (URL or bare W id): look up to get DOI, try to upgrade to S2
        m = OPENALEX_URL.match(text) or OPENALEX_ID.match(text)
        if m:
            work_id = (
                m.group("id") if hasattr(m, "group") and "id" in m.groupdict() else text
            )
            payload = await _openalex_lookup(client, work_id)
            if payload:
                oa_ref = _ref_from_openalex(payload)
                if oa_ref.doi:
                    s2 = await _s2_lookup(client, f"DOI:{oa_ref.doi}")
                    if s2 and s2.get("paperId"):
                        return _ref_from_s2(s2, source="semantic_scholar")
                return oa_ref
            return CanonicalRef(
                source="openalex",
                external_id=work_id,
                paper_id=f"OA:{work_id}",
            )

        # 3) arXiv URL / ID — S2 supports the arXiv: prefix directly
        m = ARXIV_URL.match(text) or ARXIV_ID.match(text)
        if m:
            arxiv_id = (
                m.group("id") if hasattr(m, "group") and "id" in m.groupdict() else text
            )
            # Strip any trailing version suffix for S2 lookup
            arxiv_id_bare = re.sub(r"v\d+$", "", arxiv_id)
            payload = await _s2_lookup(client, f"arXiv:{arxiv_id_bare}")
            if payload and payload.get("paperId"):
                return _ref_from_s2(payload, source="semantic_scholar")

            # S2 missed (often a free-tier 429/403). Enrich via the arXiv Atom API
            # so the fetcher has at least title + maybe DOI to work with.
            meta = await _arxiv_metadata(client, arxiv_id_bare)
            if meta and meta.get("doi"):
                doi_lower = meta["doi"].lower()
                payload = await _s2_lookup(client, f"DOI:{doi_lower}")
                if payload and payload.get("paperId"):
                    return _ref_from_s2(payload, source="semantic_scholar")
                payload = await _openalex_lookup(client, f"https://doi.org/{doi_lower}")
                if payload:
                    return _ref_from_openalex(payload)
                return CanonicalRef(
                    source="arxiv",
                    external_id=arxiv_id_bare,
                    paper_id=f"ARX:{arxiv_id_bare}",
                    doi=doi_lower,
                    title=meta.get("title"),
                    year=meta.get("year"),
                    url=f"https://arxiv.org/abs/{arxiv_id_bare}",
                )
            return CanonicalRef(
                source="arxiv",
                external_id=arxiv_id_bare,
                paper_id=f"ARX:{arxiv_id_bare}",
                title=(meta or {}).get("title"),
                year=(meta or {}).get("year"),
                url=f"https://arxiv.org/abs/{arxiv_id_bare}",
            )

        # 4) DOI (URL or bare) — try S2 first, then OpenAlex
        m = DOI_URL.match(text)
        if m:
            doi = m.group("doi")
        elif DOI_BARE.match(text):
            doi = text
        else:
            doi = None

        if doi:
            doi_lower = doi.lower()
            payload = await _s2_lookup(client, f"DOI:{doi_lower}")
            if payload and payload.get("paperId"):
                return _ref_from_s2(payload, source="semantic_scholar")
            payload = await _openalex_lookup(client, f"https://doi.org/{doi_lower}")
            if payload:
                return _ref_from_openalex(payload)
            return CanonicalRef(
                source="doi",
                external_id=doi_lower,
                paper_id=f"DOI:{doi_lower}",
                doi=doi_lower,
            )

        return None
    finally:
        if owns_client:
            await client.aclose()
