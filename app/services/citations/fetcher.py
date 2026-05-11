from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

import httpx

from app.services.citations.resolver import (
    CanonicalRef,
    SEMANTIC_SCHOLAR_BASE,
    OPENALEX_BASE,
    _openalex_headers,
    _s2_headers,
)


logger = logging.getLogger(__name__)


# Hard ceiling that keeps any single build well inside S2 free-tier limits.
_SEMAPHORE = asyncio.Semaphore(4)
RETRY_BACKOFF_SECONDS = 1.5
SPARSE_REF_THRESHOLD = 5  # if S2 returns fewer than this for both arrays, try OpenAlex


S2_DETAIL_FIELDS = (
    "paperId,externalIds,title,year,authors.name,citationCount,url,venue,"
    "references.paperId,references.externalIds,references.title,references.year,"
    "references.authors.name,references.citationCount,references.url,"
    "citations.paperId,citations.externalIds,citations.title,citations.year,"
    "citations.authors.name,citations.citationCount,citations.url"
)

OPENALEX_LIST_SELECT = "id,doi,display_name,publication_year,authorships,cited_by_count"


@dataclass
class Node:
    paper_id: str
    title: str
    year: Optional[int] = None
    authors: List[str] = field(default_factory=list)
    citation_count: Optional[int] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    sources: List[str] = field(default_factory=list)


@dataclass
class OneHopPayload:
    seed: Node
    references: List[Node]
    citers: List[Node]
    sources_used: List[str]


ProgressCallback = Optional[Callable[[dict], Awaitable[None]]]


async def _emit(on_progress: ProgressCallback, event: dict) -> None:
    if on_progress is None:
        return
    try:
        await on_progress(event)
    except Exception:
        logger.exception("Progress callback raised; continuing")


async def _request(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    on_progress: ProgressCallback = None,
    source_label: str = "",
) -> Optional[dict]:
    """GET with exponential backoff for 429/5xx; returns parsed JSON or None."""
    async with _SEMAPHORE:
        for attempt in range(3):
            try:
                response = await client.get(
                    url, params=params or {}, headers=headers or {}
                )
                if response.status_code == 200:
                    return response.json()
                if response.status_code in (429, 500, 502, 503, 504):
                    if attempt < 2:
                        delay = RETRY_BACKOFF_SECONDS * (2 ** attempt)
                        await asyncio.sleep(delay)
                        continue
                    await _emit(
                        on_progress,
                        {
                            "type": "warning",
                            "code": f"{source_label}_rate_limited",
                            "message": f"{source_label or 'upstream'} responded {response.status_code}",
                        },
                    )
                    return None
                logger.warning("%s returned %s for %s", source_label, response.status_code, url)
                return None
            except (httpx.RequestError, ValueError) as exc:
                if attempt < 2:
                    await asyncio.sleep(RETRY_BACKOFF_SECONDS * (2 ** attempt))
                    continue
                logger.warning("%s request failed: %s", source_label, exc)
                return None
        return None


# ----------------------------- normalization ------------------------------


def _normalize_authors(items: List[dict]) -> List[str]:
    names: List[str] = []
    for entry in items or []:
        name = (entry or {}).get("name") or (entry or {}).get("author", {}).get("display_name")
        if isinstance(name, str):
            name = name.strip()
            if name:
                names.append(name)
        if len(names) >= 6:
            break
    return names


def _strip_oa_id(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str):
        return None
    return value.rsplit("/", 1)[-1] or None


def _strip_doi(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str):
        return None
    v = value.strip()
    if v.startswith("https://doi.org/"):
        v = v.split("https://doi.org/", 1)[1]
    elif v.startswith("http://doi.org/"):
        v = v.split("http://doi.org/", 1)[1]
    return v.lower() or None


def _node_from_s2(item: dict, source_label: str = "semantic_scholar") -> Optional[Node]:
    if not isinstance(item, dict):
        return None
    paper_id = item.get("paperId")
    title = (item.get("title") or "").strip()
    if not paper_id and not title:
        return None
    external_ids = item.get("externalIds") or {}
    doi = external_ids.get("DOI") or external_ids.get("doi")
    return Node(
        paper_id=paper_id or (f"DOI:{doi.lower()}" if doi else f"TTL:{title.lower()}"),
        title=title or "(untitled)",
        year=item.get("year"),
        authors=_normalize_authors(item.get("authors") or []),
        citation_count=item.get("citationCount"),
        doi=_strip_doi(doi),
        url=item.get("url"),
        sources=[source_label],
    )


def _node_from_openalex(item: dict) -> Optional[Node]:
    if not isinstance(item, dict):
        return None
    work_id = _strip_oa_id(item.get("id"))
    title = (item.get("display_name") or item.get("title") or "").strip()
    if not work_id and not title:
        return None
    doi = _strip_doi(item.get("doi"))
    authorships = item.get("authorships") or []
    authors: List[str] = []
    for entry in authorships:
        person = (entry or {}).get("author") or {}
        name = (person.get("display_name") or "").strip()
        if name:
            authors.append(name)
        if len(authors) >= 6:
            break
    return Node(
        paper_id=f"OA:{work_id}" if work_id else (f"DOI:{doi}" if doi else f"TTL:{title.lower()}"),
        title=title or "(untitled)",
        year=item.get("publication_year"),
        authors=authors,
        citation_count=item.get("cited_by_count"),
        doi=doi,
        url=(item.get("primary_location") or {}).get("landing_page_url"),
        sources=["openalex"],
    )


def _merge_node(into: Node, other: Node) -> Node:
    """Merge `other` into `into`, preferring S2 paper_id when present and accumulating sources."""
    preferred_id = into.paper_id
    if not preferred_id.startswith(("OA:", "DOI:", "TTL:", "ARX:")):
        # S2 paperIds are 40-char hex — keep them.
        preferred_id = into.paper_id
    elif not other.paper_id.startswith(("OA:", "DOI:", "TTL:", "ARX:")):
        preferred_id = other.paper_id

    def _pick(a, b):
        if a is None:
            return b
        if b is None:
            return a
        if isinstance(a, str) and isinstance(b, str) and len(b) > len(a):
            return b
        return a

    merged_sources = list(dict.fromkeys([*into.sources, *other.sources]))
    return Node(
        paper_id=preferred_id,
        title=_pick(into.title, other.title) or into.title,
        year=_pick(into.year, other.year),
        authors=into.authors or other.authors,
        citation_count=_pick(into.citation_count, other.citation_count),
        doi=_pick(into.doi, other.doi),
        url=_pick(into.url, other.url),
        sources=merged_sources,
    )


def _dedup_extend(target: Dict[str, Node], extra: List[Node]) -> None:
    """Merge `extra` into `target` keyed by best-effort identity."""
    for node in extra:
        existing_key = None
        # 1) exact paper_id match
        if node.paper_id in target:
            existing_key = node.paper_id
        else:
            # 2) match by DOI
            if node.doi:
                for key, existing in target.items():
                    if existing.doi and existing.doi == node.doi:
                        existing_key = key
                        break
            # 3) match by (title.lower(), year)
            if existing_key is None:
                title_key = (node.title or "").strip().lower()
                if title_key:
                    for key, existing in target.items():
                        if (existing.title or "").strip().lower() == title_key and existing.year == node.year:
                            existing_key = key
                            break

        if existing_key is None:
            target[node.paper_id] = node
        else:
            target[existing_key] = _merge_node(target[existing_key], node)


# ------------------------------- S2 path ----------------------------------


async def _s2_fetch_detail(
    client: httpx.AsyncClient,
    ref: CanonicalRef,
    on_progress: ProgressCallback,
) -> Optional[dict]:
    # Choose the prefixed lookup form S2 supports.
    if ref.source == "semantic_scholar" and ref.paper_id and not ref.paper_id.startswith(("OA:", "DOI:", "ARX:", "TTL:")):
        identifier = ref.paper_id
    elif ref.doi:
        identifier = f"DOI:{ref.doi}"
    elif ref.source == "arxiv":
        identifier = f"arXiv:{ref.external_id}"
    elif ref.paper_id.startswith("ARX:"):
        identifier = f"arXiv:{ref.paper_id[4:]}"
    else:
        return None

    url = f"{SEMANTIC_SCHOLAR_BASE}/paper/{identifier}"
    return await _request(
        client,
        url,
        params={"fields": S2_DETAIL_FIELDS},
        headers=_s2_headers(),
        on_progress=on_progress,
        source_label="s2",
    )


def _parse_s2_payload(payload: dict, *, max_refs: int, max_citers: int) -> Tuple[Node, List[Node], List[Node]]:
    seed = _node_from_s2(payload) or Node(
        paper_id=payload.get("paperId") or "UNKNOWN",
        title=(payload.get("title") or "(untitled)"),
    )
    seed.sources = ["semantic_scholar"]

    refs: List[Node] = []
    for item in (payload.get("references") or [])[:max_refs]:
        node = _node_from_s2(item)
        if node:
            refs.append(node)

    citers: List[Node] = []
    for item in (payload.get("citations") or [])[:max_citers]:
        node = _node_from_s2(item)
        if node:
            citers.append(node)

    return seed, refs, citers


# ---------------------------- OpenAlex path -------------------------------


async def _openalex_resolve_work_id(
    client: httpx.AsyncClient,
    ref: CanonicalRef,
    on_progress: ProgressCallback,
) -> Optional[str]:
    if ref.source == "openalex" and ref.external_id:
        return ref.external_id
    if ref.doi:
        url = f"{OPENALEX_BASE}/works/https://doi.org/{ref.doi}"
        payload = await _request(client, url, headers=_openalex_headers(), on_progress=on_progress, source_label="openalex")
        if payload:
            return _strip_oa_id(payload.get("id"))
    # Last-resort: title search. Only confident if the top hit's title matches.
    if ref.title:
        payload = await _request(
            client,
            f"{OPENALEX_BASE}/works",
            params={
                "search": ref.title,
                "per-page": 3,
                "select": "id,display_name,publication_year,doi",
            },
            headers=_openalex_headers(),
            on_progress=on_progress,
            source_label="openalex",
        )
        ref_title_norm = ref.title.strip().lower()
        for candidate in (payload or {}).get("results", []):
            candidate_title = (candidate.get("display_name") or "").strip().lower()
            if not candidate_title:
                continue
            year_match = ref.year is None or candidate.get("publication_year") == ref.year
            if candidate_title == ref_title_norm and year_match:
                return _strip_oa_id(candidate.get("id"))
        # Fall back to the top hit only if title is a near-match (substring).
        for candidate in (payload or {}).get("results", []):
            candidate_title = (candidate.get("display_name") or "").strip().lower()
            if not candidate_title:
                continue
            if ref_title_norm in candidate_title or candidate_title in ref_title_norm:
                return _strip_oa_id(candidate.get("id"))
    return None


async def _openalex_fetch(
    client: httpx.AsyncClient,
    ref: CanonicalRef,
    *,
    max_refs: int,
    max_citers: int,
    on_progress: ProgressCallback,
) -> Tuple[Optional[Node], List[Node], List[Node]]:
    work_id = await _openalex_resolve_work_id(client, ref, on_progress)
    if not work_id:
        return None, [], []

    seed_payload = await _request(
        client,
        f"{OPENALEX_BASE}/works/{work_id}",
        headers=_openalex_headers(),
        on_progress=on_progress,
        source_label="openalex",
    )
    if not seed_payload:
        return None, [], []
    seed_node = _node_from_openalex(seed_payload)

    ref_urls = seed_payload.get("referenced_works") or []
    refs: List[Node] = []
    if ref_urls:
        # OpenAlex supports OR filter on multiple ids; chunk into groups of 50.
        chunk_size = 50
        for start in range(0, min(len(ref_urls), max_refs), chunk_size):
            chunk = ref_urls[start : start + chunk_size]
            ids_param = "|".join(_strip_oa_id(u) or "" for u in chunk if _strip_oa_id(u))
            if not ids_param:
                continue
            payload = await _request(
                client,
                f"{OPENALEX_BASE}/works",
                params={
                    "filter": f"openalex_id:{ids_param}",
                    "per-page": chunk_size,
                    "select": OPENALEX_LIST_SELECT,
                },
                headers=_openalex_headers(),
                on_progress=on_progress,
                source_label="openalex",
            )
            for item in (payload or {}).get("results", []):
                node = _node_from_openalex(item)
                if node:
                    refs.append(node)
            if len(refs) >= max_refs:
                break

    citers_payload = await _request(
        client,
        f"{OPENALEX_BASE}/works",
        params={
            "filter": f"cites:{work_id}",
            "per-page": min(max_citers, 200),
            "select": OPENALEX_LIST_SELECT,
        },
        headers=_openalex_headers(),
        on_progress=on_progress,
        source_label="openalex",
    )
    citers: List[Node] = []
    for item in (citers_payload or {}).get("results", []):
        node = _node_from_openalex(item)
        if node:
            citers.append(node)

    return seed_node, refs[:max_refs], citers[:max_citers]


# ------------------------------ public API --------------------------------


async def fetch_one_hop(
    ref: CanonicalRef,
    *,
    on_progress: ProgressCallback = None,
    max_refs: int = 200,
    max_citers: int = 200,
    client: Optional[httpx.AsyncClient] = None,
) -> OneHopPayload:
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=20.0)

    sources_used: List[str] = []
    try:
        await _emit(on_progress, {"type": "progress", "stage": "resolve_seed", "message": "Looking up seed paper"})

        s2_payload = await _s2_fetch_detail(client, ref, on_progress)

        seed: Optional[Node] = None
        refs_dict: Dict[str, Node] = {}
        citers_dict: Dict[str, Node] = {}

        if s2_payload:
            sources_used.append("semantic_scholar")
            await _emit(on_progress, {"type": "progress", "stage": "fetch_refs", "message": "Reading Semantic Scholar references"})
            s2_seed, s2_refs, s2_citers = _parse_s2_payload(
                s2_payload, max_refs=max_refs, max_citers=max_citers
            )
            seed = s2_seed
            _dedup_extend(refs_dict, s2_refs)
            await _emit(on_progress, {"type": "count", "nodes": 1 + len(refs_dict), "edges": len(refs_dict)})
            await _emit(on_progress, {"type": "progress", "stage": "fetch_citers", "message": "Reading Semantic Scholar citers"})
            _dedup_extend(citers_dict, s2_citers)
            await _emit(
                on_progress,
                {"type": "count", "nodes": 1 + len(refs_dict) + len(citers_dict), "edges": len(refs_dict) + len(citers_dict)},
            )

        # Decide whether to call OpenAlex as a fallback / enrichment.
        s2_was_sparse = (
            s2_payload is not None
            and (len(refs_dict) < SPARSE_REF_THRESHOLD and len(citers_dict) < SPARSE_REF_THRESHOLD)
            and (s2_payload.get("citationCount") or 0) > SPARSE_REF_THRESHOLD
        )
        need_openalex = s2_payload is None or s2_was_sparse

        if need_openalex:
            if s2_payload is None:
                await _emit(
                    on_progress,
                    {"type": "warning", "code": "s2_unavailable_fallback_openalex", "message": "Falling back to OpenAlex"},
                )
            await _emit(on_progress, {"type": "progress", "stage": "fetch_refs", "message": "Reading OpenAlex references"})
            oa_seed, oa_refs, oa_citers = await _openalex_fetch(
                client, ref, max_refs=max_refs, max_citers=max_citers, on_progress=on_progress
            )
            if oa_seed or oa_refs or oa_citers:
                sources_used.append("openalex")
            if seed is None and oa_seed is not None:
                seed = oa_seed
            elif seed is not None and oa_seed is not None:
                seed = _merge_node(seed, oa_seed)
            _dedup_extend(refs_dict, oa_refs)
            _dedup_extend(citers_dict, oa_citers)
            await _emit(on_progress, {"type": "progress", "stage": "fetch_citers", "message": "Reading OpenAlex citers"})
            await _emit(
                on_progress,
                {"type": "count", "nodes": 1 + len(refs_dict) + len(citers_dict), "edges": len(refs_dict) + len(citers_dict)},
            )

        if seed is None:
            seed = Node(
                paper_id=ref.paper_id or "UNKNOWN",
                title=ref.title or "(untitled)",
                year=ref.year,
                doi=ref.doi,
                url=ref.url,
                sources=[ref.source] if ref.source else [],
            )

        # When the seed came in from arXiv, the resolver's metadata is authoritative
        # for title / year / doi — OpenAlex has stale or republished records for some
        # preprints (e.g. "Attention Is All You Need" listed as 2025).
        if ref.source == "arxiv":
            if ref.title:
                seed.title = ref.title
            if ref.year is not None:
                seed.year = ref.year
            if ref.doi and not seed.doi:
                seed.doi = ref.doi
            if ref.url and not seed.url:
                seed.url = ref.url

        # If the same paper appears in both refs and citers, drop it from citers
        # and keep the ref edge (with an extra cite edge handled by the graph builder).
        for shared_id in list(refs_dict.keys() & citers_dict.keys()):
            citers_dict.pop(shared_id, None)

        await _emit(on_progress, {"type": "progress", "stage": "merge", "message": "Merging and deduplicating"})

        return OneHopPayload(
            seed=seed,
            references=list(refs_dict.values())[:max_refs],
            citers=list(citers_dict.values())[:max_citers],
            sources_used=list(dict.fromkeys(sources_used)),
        )
    finally:
        if owns_client:
            await client.aclose()
