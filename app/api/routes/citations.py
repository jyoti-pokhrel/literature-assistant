from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_current_user, get_optional_user
from app.schemas.citation import (
    CitationEdge,
    CitationNode,
    ExpandRequest,
    ExpandResponse,
    NetworkRequest,
    ResolveRequest,
    ResolveResponse,
)
from app.services.citations.cache import get_cached, put_cached
from app.services.citations.fetcher import OneHopPayload, fetch_one_hop
from app.services.citations.graph_builder import build_digraph, serialize
from app.services.citations.resolver import CanonicalRef, resolve_input


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/citations", tags=["Citations"])


def _seed_meta_from_ref(ref: CanonicalRef) -> dict:
    return {
        "title": ref.title,
        "doi": ref.doi,
        "year": ref.year,
        "url": ref.url,
        "source": ref.source,
    }


def _payload_to_seed_meta(graph_payload: dict) -> dict:
    for node in graph_payload.get("nodes", []):
        if node.get("role") == "seed":
            return {
                "title": node.get("title"),
                "doi": node.get("doi"),
                "year": node.get("year"),
                "url": node.get("url"),
            }
    return {}


def _serialize_one_hop(payload: OneHopPayload) -> dict:
    graph = build_digraph(payload)
    return serialize(graph, sources_used=payload.sources_used)


@router.post(
    "/resolve",
    response_model=ResolveResponse,
    status_code=status.HTTP_200_OK,
    summary="Resolve a paper URL or DOI to a canonical identifier",
)
async def resolve_endpoint(
    body: ResolveRequest,
    _user: dict | None = Depends(get_optional_user),
) -> ResolveResponse:
    async with httpx.AsyncClient(timeout=10.0) as client:
        ref = await resolve_input(body.input, client=client)
    if ref is None or not ref.paper_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not recognize that as a DOI, arXiv ID, or paper URL.",
        )
    return ResolveResponse(
        paper_id=ref.paper_id,
        source=ref.source,
        doi=ref.doi,
        title=ref.title,
        year=ref.year,
        url=ref.url,
    )


async def _build_and_stream(
    paper_id: str,
    queue: asyncio.Queue,
) -> None:
    """Run the cache-or-build pipeline and push NDJSON events onto `queue`."""

    async def _emit(event: dict) -> None:
        await queue.put(event)

    try:
        await _emit({"type": "progress", "stage": "cache_lookup", "message": "Checking cache"})
        cached = await get_cached(paper_id)
        if cached and cached.get("hop1"):
            await _emit({"type": "progress", "stage": "cache_hit", "message": "Served from cache"})
            payload = dict(cached["hop1"])
            payload["cached"] = True
            await _emit({"type": "result", "data": payload})
            return

        # Need to build: resolve the paper_id back into a CanonicalRef-equivalent.
        ref = await _ref_from_paper_id(paper_id)
        if ref is None:
            await _emit({"type": "error", "detail": "Could not resolve paper_id"})
            return

        payload = await fetch_one_hop(ref, on_progress=_emit)
        graph_payload = _serialize_one_hop(payload)

        await _emit({"type": "progress", "stage": "cache_write", "message": "Caching network"})
        await put_cached(
            paper_id,
            graph_payload,
            seed_meta=_seed_meta_from_ref(ref) or _payload_to_seed_meta(graph_payload),
        )

        graph_payload_out = dict(graph_payload)
        graph_payload_out["cached"] = False
        await _emit({"type": "result", "data": graph_payload_out})
    except Exception as exc:
        logger.exception("Citation network build failed: %s", exc)
        await _emit({"type": "error", "detail": str(exc)})
    finally:
        await _emit({"type": "done"})


async def _ref_from_paper_id(paper_id: str) -> Optional[CanonicalRef]:
    """Reconstruct a CanonicalRef from an internal paper_id without re-prompting the user.

    Accepts the same string the resolver hands out: an S2 hash, `DOI:<doi>`, `ARX:<id>`,
    or `OA:<W…>`. Falls back to the generic resolver for safety.
    """
    pid = (paper_id or "").strip()
    if not pid:
        return None
    if pid.startswith("DOI:"):
        return await resolve_input(pid[4:])
    if pid.startswith("ARX:"):
        return await resolve_input(pid[4:])
    if pid.startswith("OA:"):
        return await resolve_input(pid[3:])
    if len(pid) == 40 and all(c in "0123456789abcdef" for c in pid.lower()):
        return CanonicalRef(source="semantic_scholar", external_id=pid, paper_id=pid)
    # Last resort: treat as opaque and let the resolver try.
    return await resolve_input(pid)


@router.post(
    "/network",
    status_code=status.HTTP_200_OK,
    summary="Build a 1-hop citation network with streamed progress",
)
async def network_endpoint(
    body: NetworkRequest,
    _user: dict | None = Depends(get_optional_user),
) -> StreamingResponse:
    queue: asyncio.Queue = asyncio.Queue()

    async def runner() -> None:
        await _build_and_stream(body.paper_id, queue)

    async def event_stream():
        task = asyncio.create_task(runner())
        try:
            while True:
                event = await queue.get()
                yield json.dumps(event, default=str) + "\n"
                if event.get("type") == "done":
                    break
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.post(
    "/network/{paper_id}/expand",
    response_model=ExpandResponse,
    status_code=status.HTTP_200_OK,
    summary="Expand one hop from an already-known node",
)
async def expand_endpoint(
    paper_id: str,
    body: ExpandRequest,
    _user: dict | None = Depends(get_optional_user),
) -> ExpandResponse:
    # `paper_id` is the original seed; `node_id` is the node we want to expand.
    target = body.node_id
    cached = await get_cached(target)
    if cached and cached.get("hop1"):
        graph_payload = cached["hop1"]
    else:
        ref = await _ref_from_paper_id(target)
        if ref is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not resolve node_id for expansion",
            )
        payload = await fetch_one_hop(ref)
        graph_payload = _serialize_one_hop(payload)
        await put_cached(target, graph_payload, seed_meta=_seed_meta_from_ref(ref))

    known = set(body.known_ids or [])
    direction = body.direction
    edges_in_payload = graph_payload.get("edges", [])
    nodes_by_id = {n["id"]: n for n in graph_payload.get("nodes", [])}

    keep_edges = []
    for edge in edges_in_payload:
        kind = edge.get("kind")
        if kind == "ref" and edge.get("source") == target and direction in ("ref", "both"):
            keep_edges.append(edge)
        elif kind == "cite" and edge.get("target") == target and direction in ("cite", "both"):
            keep_edges.append(edge)

    added_node_ids = set()
    added_nodes_payload = []
    for edge in keep_edges:
        for endpoint in (edge.get("source"), edge.get("target")):
            if endpoint and endpoint != target and endpoint not in known and endpoint not in added_node_ids:
                node_payload = nodes_by_id.get(endpoint)
                if not node_payload:
                    continue
                added_nodes_payload.append(node_payload)
                added_node_ids.add(endpoint)

    added_edges_payload = [
        edge
        for edge in keep_edges
        if edge.get("source") in added_node_ids or edge.get("target") in added_node_ids or edge.get("source") == target or edge.get("target") == target
    ]
    # Drop edges where both endpoints are already known and identical to existing known links.
    added_edges_payload = [
        edge
        for edge in added_edges_payload
        if not (edge.get("source") in known and edge.get("target") in known)
    ]

    added_nodes = [CitationNode(**n) for n in added_nodes_payload]
    added_edges = [CitationEdge(**e) for e in added_edges_payload]
    return ExpandResponse(added_nodes=added_nodes, added_edges=added_edges)
