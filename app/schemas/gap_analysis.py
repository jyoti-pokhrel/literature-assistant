import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class SupportingPaperRef(BaseModel):
    paper_id: Optional[str] = None
    title: str
    year: Optional[int] = None
    citation_count: Optional[int] = None
    source: Optional[str] = None
    venue: Optional[str] = None


class GapEvidence(BaseModel):
    support_count: int = 0
    recent_support_count: int = 0
    influential_support_count: int = 0
    recurring_limitations: list[str] = Field(default_factory=list)
    recurring_future_work: list[str] = Field(default_factory=list)
    dominant_assumptions: list[str] = Field(default_factory=list)
    missing_metrics: list[str] = Field(default_factory=list)
    missing_datasets: list[str] = Field(default_factory=list)
    weak_baselines: list[str] = Field(default_factory=list)
    supporting_papers: list[SupportingPaperRef] = Field(default_factory=list)


class CandidateGap(BaseModel):
    gap_id: str
    category: Literal["problem_coverage", "methodology", "evaluation", "deployment"]
    title: str
    statement: str
    why_it_matters: str
    actionable_opportunity: str
    evidence: GapEvidence
    support_score: float = 0.0
    severity_score: float = 0.0
    actionability_score: float = 0.0
    novelty_score: float = 0.0
    citation_confidence_score: float = 0.0
    overall_score: float = 0.0


class EvidenceSummary(BaseModel):
    top_methods: list[str] = Field(default_factory=list)
    top_datasets: list[str] = Field(default_factory=list)
    top_metrics: list[str] = Field(default_factory=list)
    top_assumptions: list[str] = Field(default_factory=list)
    top_limitations: list[str] = Field(default_factory=list)
    top_future_work_themes: list[str] = Field(default_factory=list)


class GapAnalysisRequest(BaseModel):
    topic: str = Field(..., examples=["multi agent rl"])
    year: Optional[str] = Field(default=None, examples=["2025", "2023-2026"])
    venue: Optional[str] = Field(default=None, examples=["NeurIPS", "ICLR"])
    strict_venue: bool = Field(default=False, examples=[False])
    max_results: int = Field(default=10, examples=[10])
    top_k_gaps: int = Field(default=5, examples=[5])

    @field_validator("topic")
    @classmethod
    def validate_topic(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Topic must be at least 3 characters")
        return value

    @field_validator("year")
    @classmethod
    def validate_year(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None

        value = value.strip()
        if not value or value.lower() in {"string", "none", "null", "undefined", "all", "any"}:
            return None

        exact_match = re.fullmatch(r"\d{4}", value)
        range_match = re.fullmatch(r"(\d{4})\s*-\s*(\d{4})", value)

        if exact_match:
            if int(value) < 1:
                raise ValueError("year must be a positive integer")
            return value

        if range_match:
            start_year = int(range_match.group(1))
            end_year = int(range_match.group(2))
            if start_year < 1 or end_year < 1:
                raise ValueError("year range must contain positive integers")
            if start_year > end_year:
                raise ValueError("year range start must be less than or equal to end")
            return f"{start_year}-{end_year}"

        raise ValueError("year must be a 4 digit year or a range like 2023-2026")

    @field_validator("venue")
    @classmethod
    def validate_venue(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if not value or value.lower() in {"string", "none", "null", "undefined", "all", "any"}:
            return None
        return value

    @field_validator("max_results")
    @classmethod
    def validate_max_results(cls, value: int) -> int:
        if value < 1 or value > 50:
            raise ValueError("max_results must be between 1 and 50")
        return value

    @field_validator("top_k_gaps")
    @classmethod
    def validate_top_k_gaps(cls, value: int) -> int:
        if value < 1 or value > 10:
            raise ValueError("top_k_gaps must be between 1 and 10")
        return value


class GapAnalysisResponse(BaseModel):
    topic: str
    filters: dict
    sources_used: list[str]
    papers_analyzed: int
    evidence_summary: EvidenceSummary
    gaps: list[CandidateGap] = Field(default_factory=list)
