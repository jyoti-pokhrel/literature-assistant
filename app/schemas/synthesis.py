from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


def sanitize_string(v: Any) -> str:
    if v is None:
        return ""

    s = str(v)
    s = re.sub(r"(?i)\bundefined\b", "", s)
    s = s.strip()
    if not s or s.lower() in {"null", "none"}:
        return ""

    lower_s = s.lower()
    junk_patterns = {
        "null",
        "[object object]",
        "none",
        "n/a",
        "unknown",
        "string",
        "empty",
        "all",
        "any",
        "npt",
        "javascript:void(0)",
        "void(0)",
        "not available",
        "no information",
    }
    if lower_s in junk_patterns:
        return ""

    return s


# Core models


class CitationRef(BaseModel):
    paper_id: Optional[str] = None
    title: str
    year: Optional[int] = None
    source: Optional[str] = None
    venue: str = "Unknown Venue"
    citation_count: int = 0
    url: Optional[str] = None
    extracted_evidence: List[str] = Field(default_factory=list)

    @field_validator("venue", "title", "source", "url", mode="before")
    @classmethod
    def sanitize_metadata(cls, v: Any) -> str:
        res = sanitize_string(v)
        return res if res else ""

    @field_validator("extracted_evidence", mode="before")
    @classmethod
    def sanitize_evidence(cls, v: Any) -> List[str]:
        if not isinstance(v, list):
            return []
        return [sanitize_string(i) for i in v if sanitize_string(i)]


class SynthesisGap(BaseModel):
    gap_id: str
    gap_title: str
    description: str
    what_fails: str
    why_it_exists: str
    missing_piece: str
    pattern_detected: str
    proposed_direction: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    cluster_id: int = -1
    supporting_papers: List[str] = Field(default_factory=list)
    citations: List[CitationRef] = Field(default_factory=list)
    score_breakdown: Dict[str, float] = Field(default_factory=dict)
    citation_validation: Dict[str, Any] = Field(default_factory=dict)
    cross_paper_validation: Dict[str, Any] = Field(default_factory=dict)
    llm_verification: Dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "gap_title",
        "description",
        "what_fails",
        "why_it_exists",
        "missing_piece",
        "pattern_detected",
        "proposed_direction",
        mode="before",
    )
    @classmethod
    def sanitize_gap_fields(cls, v: Any) -> str:
        return sanitize_string(v)


class ClusterSummary(BaseModel):
    """Summarises one HDBSCAN cluster — returned in SynthesisResponse.clusters[]."""

    cluster_id: int
    theme_label: str = "unspecified"
    paper_count: int = 0
    top_limitations: List[str] = Field(default_factory=list)
    top_future_work: List[str] = Field(default_factory=list)
    gap_id: Optional[str] = None  # linked SynthesisGap.gap_id
    papers: List[Dict[str, Any]] = Field(
        default_factory=list
    )  # papers with x/y for the literature map
    trend_status: str = "Established"

    @field_validator("theme_label", mode="before")
    @classmethod
    def sanitize_theme(cls, v: Any) -> str:
        return sanitize_string(v) or "unspecified"


class PatternAnalysis(BaseModel):
    top_methods: List[str] = Field(default_factory=list)
    top_datasets: List[str] = Field(default_factory=list)
    top_metrics: List[str] = Field(default_factory=list)
    top_limitations: List[str] = Field(default_factory=list)
    top_future_work: List[str] = Field(default_factory=list)
    method_trend_by_year: Dict[str, List[str]] = Field(default_factory=dict)
    dataset_frequency: Dict[str, int] = Field(default_factory=dict)
    metric_frequency: Dict[str, int] = Field(default_factory=dict)
    baseline_stagnation: bool = False
    emerging_opportunities: List[str] = Field(default_factory=list)
    saturated_areas: List[str] = Field(default_factory=list)

    @field_validator(
        "top_methods",
        "top_datasets",
        "top_metrics",
        "top_limitations",
        "top_future_work",
        "emerging_opportunities",
        "saturated_areas",
        mode="before",
    )
    @classmethod
    def sanitize_list_fields(cls, v: Any) -> List[str]:
        if not isinstance(v, list):
            if isinstance(v, str):
                val = sanitize_string(v)
                return [val] if val else []
            return []
        return [sanitize_string(item) for item in v if sanitize_string(item)]


class VisualizationData(BaseModel):
    # Static base64-encoded PNG charts (for PDF embedding)
    umap_scatter: Optional[str] = None
    confidence_bars: Optional[str] = None
    year_distribution: Optional[str] = None
    method_trends: Optional[str] = None
    dataset_frequency: Optional[str] = None
    metric_frequency: Optional[str] = None

    # Interactive Plotly JSON charts (for frontend)
    plotly_umap: Optional[Dict[str, Any]] = None
    plotly_dataset_freq: Optional[Dict[str, Any]] = None
    plotly_metric_freq: Optional[Dict[str, Any]] = None
    plotly_confidence_bars: Optional[Dict[str, Any]] = None

    # New charts (added in synthesis rebuild)
    plotly_research_intensity: Optional[Dict[str, Any]] = None
    plotly_cluster_distribution: Optional[Dict[str, Any]] = None
    plotly_gap_frequency: Optional[Dict[str, Any]] = None
    paper_gap_mapping: Optional[Dict[str, Any]] = None

    @model_validator(mode="before")
    @classmethod
    def sanitize_viz_fields(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        cleaned: dict = {}
        for k, v in values.items():
            if isinstance(v, str):
                cleaned[k] = sanitize_string(v) or None
            else:
                cleaned[k] = v
        return cleaned


# Request / Response


class SynthesisRequest(BaseModel):
    topic: str = Field(..., min_length=3, examples=["multi agent rl"])
    year: Optional[str] = Field(default=None, examples=["2025", "2023-2026"])
    venue: Optional[str] = Field(default=None, examples=["NeurIPS", "ICLR"])
    strict_venue: bool = Field(default=False, examples=[False])
    max_results: int = Field(default=15, ge=1, le=100)
    top_k_gaps: int = Field(default=8, ge=1, le=15)
    regenerate: bool = Field(default=False, description="If true, bypasses the cache")

    @field_validator("topic")
    @classmethod
    def validate_topic(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("Topic must be at least 3 characters")
        return v

    @field_validator("year")
    @classmethod
    def validate_year(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        if not v or v.lower() in {"string", "none", "null", "undefined", "all", "any"}:
            return None
        if re.fullmatch(r"\d{4}", v):
            return v
        m = re.fullmatch(r"(\d{4})\s*-\s*(\d{4})", v)
        if m:
            if int(m.group(1)) > int(m.group(2)):
                raise ValueError("Year range start must be <= end")
            return f"{m.group(1)}-{m.group(2)}"
        raise ValueError("Year must be YYYY or YYYY-YYYY")

    @field_validator("venue")
    @classmethod
    def validate_venue(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        if not v or v.lower() in {"string", "none", "null", "undefined", "all", "any"}:
            return None
        return v


class SynthesisResponse(BaseModel):
    report_id: str
    topic: str
    filters: Dict[str, Any] = Field(default_factory=dict)
    sources_used: List[str] = Field(default_factory=list)
    sources_count: int = 0
    papers_analyzed: int = 0
    pattern_analysis: PatternAnalysis
    gaps: List[SynthesisGap] = Field(default_factory=list)
    clusters: List[ClusterSummary] = Field(default_factory=list)  # now populated
    stats: Dict[str, Any] = Field(default_factory=dict)
    visualizations: VisualizationData
    pdf_url: Optional[str] = None
    created_at: str
    success: bool = True
    share_url: Optional[str] = None
    copy_text: Optional[str] = None
    papers: List[Dict[str, Any]] = Field(default_factory=list)
    is_cached: bool = False
    generated_at: Optional[str] = None


class SynthesisHistoryItem(BaseModel):
    report_id: str
    topic: str
    papers_analyzed: int
    gap_count: int
    created_at: str


class SynthesisHistoryResponse(BaseModel):
    total: int
    items: List[SynthesisHistoryItem]
    next_cursor: Optional[str] = None


# ── Background Jobs ──────────────────────────────────────────────────────────

class JobStatusEnum(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class SynthesisJobStatus(BaseModel):
    job_id: str
    status: JobStatusEnum
    progress: int = 0
    detail: str = ""
    result: Optional[SynthesisResponse] = None
    error: Optional[str] = None
    created_at: str
    updated_at: str
