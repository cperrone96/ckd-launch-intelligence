from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr

EvidenceType = Literal["public_observed", "public_synthetic"]


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Provenance(APIModel):
    artifact: StrictStr
    sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    manifest: StrictStr
    source_manifest: StrictStr | None = None


class Evidence(APIModel):
    evidence_type: EvidenceType
    source: StrictStr
    release: StrictStr
    source_population: StrictStr
    grain: StrictStr
    source_date_or_window: StrictStr
    provenance: Provenance
    limitations: list[StrictStr] = Field(min_length=1)
    join_policy: StrictStr


class Pagination(APIModel):
    page: StrictInt = Field(ge=1)
    page_size: StrictInt = Field(ge=1, le=100)
    total: StrictInt = Field(ge=0)


class ErrorResponse(APIModel):
    code: StrictStr
    message: StrictStr
    details: dict[str, Any]


class HealthResponse(APIModel):
    status: Literal["ok"]
    service: StrictStr
    version: StrictStr
    repository: StrictStr
    evidence_boundary: StrictStr


class ScoringRequest(APIModel):
    age_years: StrictFloat = Field(ge=18, le=120)
    sex: Literal["Female", "Male"]
    race_ethnicity: Literal[
        "Mexican American",
        "Non-Hispanic Asian",
        "Non-Hispanic Black",
        "Non-Hispanic White",
        "Other Hispanic",
        "Other Race - Including Multi-Racial",
    ]


class ScoreResponse(APIModel):
    probability: StrictFloat = Field(ge=0, le=1)
    threshold: StrictFloat = Field(ge=0, le=1)
    selected: StrictBool
    intended_use: Literal["educational screening-opportunity demonstration"]
    interpretation: StrictStr
    evidence: Evidence
    limitations: list[StrictStr] = Field(min_length=1)


class CollectionResponse(APIModel):
    items: list[dict[str, Any]]
    pagination: Pagination
    evidence: Evidence


class PerformanceResponse(APIModel):
    comparison: dict[str, Any]
    evidence: Evidence


class SourcesResponse(APIModel):
    sources: list[dict[str, Any]]


class OpportunityResponse(APIModel):
    scenario_only: StrictBool
    source_panels: dict[str, list[dict[str, Any]]]
    scenario_rankings: list[dict[str, Any]]
    limitations: StrictStr
    evidence: list[Evidence]


class JourneyResponse(APIModel):
    summaries: list[dict[str, Any]]
    survival: list[dict[str, Any]]
    rules: dict[str, Any]
    evidence: Evidence
    limitations: list[StrictStr] = Field(min_length=1)
