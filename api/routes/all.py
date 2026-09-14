from __future__ import annotations

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Query, Request

from ..schemas import (
    ErrorResponse,
    HealthResponse,
    JourneyResponse,
    MEPSCollectionResponse,
    OpportunityResponse,
    PartDCollectionResponse,
    PerformanceResponse,
    PopulationEstimateCollectionResponse,
    ScoreResponse,
    ScoringRequest,
    SourcesResponse,
    TrialCollectionResponse,
    WaterfallCollectionResponse,
)
from ..services import CKDAnalyticsService

router = APIRouter(
    prefix="/api/v1",
    responses={
        422: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        405: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)


def service(request: Request) -> CKDAnalyticsService:
    return cast(CKDAnalyticsService, request.app.state.service)


@router.get("/health", response_model=HealthResponse)
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "ckd-launch-intelligence",
        "version": "1.0.0",
        "repository": "committed public artifacts only",
        "evidence_boundary": "aggregate; no patient-level cross-source joins",
    }


@router.get("/sources", response_model=SourcesResponse)
def sources(request: Request) -> dict[str, object]:
    return service(request).sources()


@router.get("/cohorts", response_model=WaterfallCollectionResponse)
def cohorts(
    request: Request,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, object]:
    return service(request).collection(
        "patient_need",
        "waterfall",
        page,
        page_size,
        population="NHANES 2017-2018",
        grain="survey-domain aggregate",
        window="2017-2018",
    )


@router.get("/population-estimates", response_model=PopulationEstimateCollectionResponse)
def population_estimates(
    request: Request,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, object]:
    return service(request).collection(
        "patient_need",
        "estimates",
        page,
        page_size,
        population="NHANES 2017-2018",
        grain="survey-domain aggregate",
        window="2017-2018",
    )


@router.get("/patient-finding/performance", response_model=PerformanceResponse)
def performance(
    request: Request,
) -> dict[str, object]:
    return service(request).performance()


@router.post("/patient-finding/score", response_model=ScoreResponse)
def score(request: Request, payload: ScoringRequest) -> dict[str, object]:
    return service(request).score(payload.model_dump())


@router.get("/utilization", response_model=MEPSCollectionResponse)
def utilization(
    request: Request,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, object]:
    return service(request).collection(
        "meps",
        "estimates",
        page,
        page_size,
        population="MEPS HC-243 2022",
        grain="HC-243 person-year consolidated aggregate",
        window="2022",
    )


@router.get("/prescribing", response_model=PartDCollectionResponse)
def prescribing(
    request: Request,
    provider_state: Annotated[str | None, Query(pattern=r"^[A-Z]{2}$")] = None,
    generic_name: Annotated[
        Literal["Dapagliflozin Propanediol", "Empagliflozin", "Finerenone"] | None,
        Query(),
    ] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, object]:
    return service(request).collection(
        "partd",
        "aggregates",
        page,
        page_size,
        filters={
            key: value
            for key, value in {
                "provider_state": provider_state,
                "generic_name": generic_name,
            }.items()
            if value is not None
        }
        or None,
        population="Medicare Part D prescriber-drug aggregates",
        grain="provider-drug-state aggregate",
        window="2024",
    )


@router.get("/geography/opportunity", response_model=OpportunityResponse)
def opportunity(request: Request) -> dict[str, object]:
    return service(request).opportunity()


@router.get("/trials", response_model=TrialCollectionResponse)
def trials(
    request: Request,
    dimension: Annotated[
        Literal[
            "geography",
            "intervention",
            "phase_or_type",
            "change_over_time",
            "status",
            "sponsor",
        ]
        | None,
        Query(),
    ] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, object]:
    key = dimension or "geography"
    return service(request).collection(
        "trials",
        key,
        page,
        page_size,
        population="registered CKD studies",
        grain="registered study aggregate",
        window="API release snapshot",
    )


@router.get("/journeys/synthetic", response_model=JourneyResponse)
def journeys(request: Request) -> dict[str, object]:
    return service(request).journeys()
