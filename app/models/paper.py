from pydantic import BaseModel, Field, field_validator
from typing import List, Optional


class Paper(BaseModel):
    paper_id: str
    title: str
    year: int
    url: Optional[str] = None

    # Problem definition
    problem: Optional[str] = None
    domain: Optional[str] = None

    # Methodology
    method: Optional[str] = None
    assumptions: List[str] = Field(default_factory=list)

    # Evaluation
    datasets: List[str] = Field(default_factory=list)
    metrics: List[str] = Field(default_factory=list)
    baselines: List[str] = Field(default_factory=list)
    key_results: Optional[str] = None

    # Weakness signals (VERY important)
    limitations: List[str] = Field(default_factory=list)
    future_work: List[str] = Field(default_factory=list)

    # Context
    abstract: Optional[str] = None

    # --- Validators ---
    @field_validator("year", mode="before")
    @classmethod
    def parse_year(cls, v):
        if v is None:
            return 0
        try:
            return int(v)
        except (ValueError, TypeError):
            return 0

    @field_validator(
        "datasets",
        "metrics",
        "baselines",
        "limitations",
        "future_work",
        "assumptions",
        mode="before",
    )
    @classmethod
    def ensure_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return v
