from __future__ import annotations

from typing import Dict, List

import networkx as nx

from app.services.citations.fetcher import Node, OneHopPayload


def build_digraph(payload: OneHopPayload) -> nx.DiGraph:
    """Build a directed citation graph rooted at the seed.

    Edges flow from citing → cited. Therefore:
      - seed → reference (seed cites the reference)
      - citer → seed     (citer cites the seed)
    """
    graph = nx.DiGraph()
    seed = payload.seed
    _add_node(graph, seed, role="seed")

    for ref in payload.references:
        _add_node(graph, ref, role="reference")
        graph.add_edge(seed.paper_id, ref.paper_id, kind="ref")

    for citer in payload.citers:
        _add_node(graph, citer, role="citer")
        graph.add_edge(citer.paper_id, seed.paper_id, kind="cite")

    return graph


def serialize(graph: nx.DiGraph, *, sources_used: List[str]) -> Dict:
    """Flatten a DiGraph into the wire shape consumed by the frontend."""
    nodes: List[Dict] = []
    for node_id, attrs in graph.nodes(data=True):
        nodes.append(
            {
                "id": node_id,
                "paper_id": node_id,
                "doi": attrs.get("doi"),
                "title": attrs.get("title") or "(untitled)",
                "year": attrs.get("year"),
                "authors": list(attrs.get("authors") or [])[:6],
                "citation_count": attrs.get("citation_count"),
                "role": attrs.get("role", "reference"),
                "sources": list(attrs.get("sources") or []),
                "url": attrs.get("url"),
            }
        )

    edges: List[Dict] = [
        {"source": src, "target": dst, "kind": data.get("kind", "ref")}
        for src, dst, data in graph.edges(data=True)
    ]

    return {"nodes": nodes, "edges": edges, "sources_used": list(sources_used)}


def _add_node(graph: nx.DiGraph, node: Node, *, role: str) -> None:
    if not node.paper_id:
        return
    if graph.has_node(node.paper_id):
        # Upgrade role: seed beats reference beats citer.
        current = graph.nodes[node.paper_id].get("role")
        if _role_rank(role) > _role_rank(current):
            graph.nodes[node.paper_id]["role"] = role
        return
    graph.add_node(
        node.paper_id,
        title=node.title,
        year=node.year,
        authors=list(node.authors),
        citation_count=node.citation_count,
        doi=node.doi,
        url=node.url,
        sources=list(node.sources),
        role=role,
    )


def _role_rank(role: str | None) -> int:
    return {"seed": 3, "reference": 2, "citer": 1}.get(role or "", 0)
