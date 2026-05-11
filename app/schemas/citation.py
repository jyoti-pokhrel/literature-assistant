from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


Role = Literal["seed", "reference", "citer"]
EdgeKind = Literal["ref", "cite"]
ExpandDirection = Literal["ref", "cite", "both"]


class CitationNode(BaseModel):
    id: str
    paper_id: str
    doi: Optional[str] = None
    title: str
    year: Optional[int] = None
    authors: List[str] = Field(default_factory=list)
    citation_count: Optional[int] = None
    role: Role
    sources: List[str] = Field(default_factory=list)
    url: Optional[str] = None


class CitationEdge(BaseModel):
    source: str
    target: str
    kind: EdgeKind


class CitationGraphPayload(BaseModel):
    nodes: List[CitationNode]
    edges: List[CitationEdge]
    sources_used: List[str] = Field(default_factory=list)
    cached: bool = False


class ResolveRequest(BaseModel):
    input: str

    @field_validator("input")
    @classmethod
    def not_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if len(v) < 4:
            raise ValueError("Paper identifier is too short")
        if len(v) > 600:
            raise ValueError("Paper identifier is too long")
        return v


class ResolveResponse(BaseModel):
    paper_id: str
    source: str
    doi: Optional[str] = None
    title: Optional[str] = None
    year: Optional[int] = None
    url: Optional[str] = None


class NetworkRequest(BaseModel):
    paper_id: str

    @field_validator("paper_id")
    @classmethod
    def not_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("paper_id is required")
        return v


class ExpandRequest(BaseModel):
    node_id: str
    direction: ExpandDirection = "both"
    known_ids: List[str] = Field(default_factory=list)

    @field_validator("node_id")
    @classmethod
    def not_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("node_id is required")
        return v


class ExpandResponse(BaseModel):
    added_nodes: List[CitationNode] = Field(default_factory=list)
    added_edges: List[CitationEdge] = Field(default_factory=list)
