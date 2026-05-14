from pydantic import BaseModel, field_validator


class Report(BaseModel):
    paper_id: str
    summary: str
    score: float

    @field_validator("score")
    def score_valid(cls, v):
        if v < 0 or v > 10:
            raise ValueError("Score must be between 0 and 10")
        return v

    @field_validator("summary")
    def summary_valid(cls, v):
        v = v.strip()
        if len(v) < 10:
            raise ValueError("Summary must be at least 10 characters")
        return v
