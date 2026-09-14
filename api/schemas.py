from __future__ import annotations

from typing import Literal

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


class ErrorLocation(APIModel):
    loc: list[StrictStr | StrictInt]
    type: StrictStr


class ErrorDetails(APIModel):
    errors: list[ErrorLocation] | None = None


class ErrorResponse(APIModel):
    code: StrictStr
    message: StrictStr
    details: ErrorDetails


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


class WaterfallItem(APIModel):
    people: StrictInt = Field(ge=0)
    stage: StrictStr
    stage_order: StrictInt = Field(ge=1)


class PopulationEstimateItem(APIModel):
    key: StrictStr
    ci_high: StrictFloat
    ci_low: StrictFloat
    confidence_level: StrictFloat
    degrees_freedom: StrictInt
    denominator: StrictInt
    design_observations: StrictInt
    excluded_missing: StrictInt
    lonely_psu_strategy: StrictStr
    point: StrictFloat
    psus: StrictInt
    source_population: StrictStr
    standard_error: StrictFloat
    strata: StrictInt
    sum_weights: StrictFloat
    unweighted_point: StrictFloat
    variance_method: StrictStr


class MEPSItem(APIModel):
    ci_high: StrictFloat
    ci_low: StrictFloat
    confidence_level: StrictFloat
    degrees_freedom: StrictInt
    denominator: StrictInt
    design_observations: StrictInt
    excluded_missing: StrictInt
    lonely_psu_strategy: StrictStr
    metric: StrictStr
    point: StrictFloat
    psus: StrictInt
    source_population: StrictStr
    standard_error: StrictFloat
    strata: StrictInt
    sum_weights: StrictFloat
    unit: StrictStr
    variance_method: StrictStr


class PartDItem(APIModel):
    brand_name: StrictStr
    generic_name: StrictStr
    provider_count: StrictInt
    provider_state: StrictStr = Field(pattern=r"^[A-Z]{2}$")
    total_30day_fills: StrictFloat
    total_claims: StrictInt
    total_drug_cost_usd: StrictFloat


class TrialItem(APIModel):
    key: StrictStr | None = None
    available_denominator: StrictInt | None = None
    country: StrictStr | None = None
    dimension: StrictStr | None = None
    evidence_type: EvidenceType
    grain: StrictStr
    intervention: StrictStr | None = None
    overall_status: StrictStr | None = None
    phase: StrictStr | None = None
    share_of_registered_studies: StrictFloat | None = None
    share_of_studies_with_intervention: StrictFloat | None = None
    share_of_studies_with_location: StrictFloat | None = None
    source: StrictStr
    sponsor: StrictStr | None = None
    study_count: StrictInt
    study_share: StrictFloat | None = None
    study_type: StrictStr | None = None
    studies_with_reported_enrollment: StrictInt | None = None
    total_reported_enrollment: StrictInt | None = None
    update_year: StrictInt | None = None


class WaterfallCollectionResponse(APIModel):
    items: list[WaterfallItem]
    pagination: Pagination
    evidence: Evidence


class PopulationEstimateCollectionResponse(APIModel):
    items: list[PopulationEstimateItem]
    pagination: Pagination
    evidence: Evidence


class MEPSCollectionResponse(APIModel):
    items: list[MEPSItem]
    pagination: Pagination
    evidence: Evidence


class PartDCollectionResponse(APIModel):
    items: list[PartDItem]
    pagination: Pagination
    evidence: Evidence


class TrialCollectionResponse(APIModel):
    items: list[TrialItem]
    pagination: Pagination
    evidence: Evidence


class SourceRecord(APIModel):
    key: StrictStr
    source: StrictStr
    release: StrictStr
    evidence_type: EvidenceType
    artifact_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")


class SourcesResponse(APIModel):
    sources: list[SourceRecord]


class MetricInterval(APIModel):
    caveat: StrictStr
    cluster_count: StrictInt
    high: StrictFloat
    low: StrictFloat
    method: StrictStr
    requested_replicates: StrictInt
    valid_replicates: StrictInt


class CalibrationBin(APIModel):
    mean_probability: StrictFloat
    n: StrictInt
    observed_rate: StrictFloat


class ConfusionMatrix(APIModel):
    false_negative: StrictInt
    false_positive: StrictInt
    true_negative: StrictInt
    true_positive: StrictInt


class ModelMetrics(APIModel):
    brier_interval: MetricInterval
    brier_score: StrictFloat
    calibration_bins: list[CalibrationBin]
    confusion_matrix: ConfusionMatrix
    mean_probability: StrictFloat
    n: StrictInt
    positives: StrictInt
    pr_auc: StrictFloat
    pr_auc_interval: MetricInterval
    precision: StrictFloat
    precision_interval: MetricInterval
    recall: StrictFloat
    recall_interval: MetricInterval
    requested_count: StrictInt
    roc_auc: StrictFloat
    roc_auc_interval: MetricInterval
    selected_count: StrictInt
    selected_share: StrictFloat
    threshold: StrictFloat
    tie_policy: StrictStr


class SubgroupMetric(APIModel):
    brier_interval: MetricInterval | None = None
    brier_score: StrictFloat
    caveat: StrictStr | None = None
    group: StrictStr
    n: StrictInt
    positives: StrictInt
    precision: StrictFloat | None = None
    precision_interval: MetricInterval | None = None
    prevalence: StrictFloat
    recall: StrictFloat
    recall_interval: MetricInterval | None = None
    value: StrictStr


class Subgroups(APIModel):
    age_band: list[SubgroupMetric]
    sex: list[SubgroupMetric]


class CohortDefinition(APIModel):
    holdout_n: StrictInt
    holdout_prevalence: StrictFloat
    target: StrictStr


class CohortSensitivityItem(APIModel):
    holdout_n: StrictInt
    holdout_prevalence: StrictFloat
    pr_auc: StrictFloat
    roc_auc: StrictFloat


class CohortSensitivity(APIModel):
    primary_definition: CohortDefinition
    sensitivity_albuminuria_only: CohortSensitivityItem
    sensitivity_egfr_only: CohortSensitivityItem


class Capacity(APIModel):
    requested_count: StrictInt
    selected_count: StrictInt
    selected_share: StrictFloat
    threshold: StrictFloat
    tie_policy: StrictStr | None = None


class Split(APIModel):
    development_group_count: StrictInt
    development_n: StrictInt
    holdout_group_count: StrictInt
    holdout_n: StrictInt
    random_state: StrictInt
    strategy: StrictStr
    threshold_source: StrictStr


class PairedDifference(APIModel):
    comparison: StrictStr
    estimate: StrictFloat
    interpretation: StrictStr
    interval: MetricInterval
    metric: StrictStr


class PairedDifferences(APIModel):
    logistic_minus_random_forest_brier_score: PairedDifference
    logistic_minus_random_forest_pr_auc: PairedDifference
    logistic_minus_random_forest_roc_auc: PairedDifference


class ModelSet(APIModel):
    logistic_regression: ModelMetrics
    prevalence_no_skill: ModelMetrics
    random_forest: ModelMetrics


class PerformanceComparison(APIModel):
    artifact_schema: StrictStr
    analysis_population: StrictStr
    outcome: StrictStr
    selected_model: StrictStr
    selection_policy: StrictStr
    selected_threshold: StrictFloat
    threshold_capacity: StrictFloat
    development_capacity: Capacity
    holdout_prevalence: StrictFloat
    holdout_n: StrictInt
    features: list[StrictStr]
    split: Split
    models: ModelSet
    subgroups: Subgroups
    cohort_sensitivity: CohortSensitivity
    paired_differences: PairedDifferences
    performance_interpretation: StrictStr
    intended_use: StrictStr
    limitations: list[StrictStr] = Field(min_length=1)


class PerformanceResponse(APIModel):
    comparison: PerformanceComparison
    evidence: Evidence


class PartDOpportunityPanel(APIModel):
    items: list[PartDItem]
    total: StrictInt = Field(ge=0)
    pagination_complete: StrictBool
    evidence: Evidence


class TrialOpportunityPanel(APIModel):
    items: list[TrialItem]
    total: StrictInt = Field(ge=0)
    pagination_complete: StrictBool
    evidence: Evidence


class OpportunityPanels(APIModel):
    prescribing_provider_state: PartDOpportunityPanel
    trials_country: TrialOpportunityPanel


class OpportunityResponse(APIModel):
    scenario_only: StrictBool
    source_panels: OpportunityPanels
    scenario_rankings: list[StrictStr]
    limitations: StrictStr
    evidence: list[Evidence] = Field(min_length=1)


class JourneySummary(APIModel):
    index_date: StrictStr
    target_date: StrictStr | None = None
    persistence_date: StrictStr | None = None
    observation_end: StrictStr
    duration_days: StrictInt
    event_observed: StrictBool
    censoring_reason: StrictStr | None = None
    has_target: StrictBool
    evidence_type: Literal["public_synthetic"]


class SurvivalRow(APIModel):
    time: StrictFloat
    at_risk: StrictInt
    events: StrictInt
    censored: StrictInt
    survival: StrictFloat
    greenwood_variance: StrictFloat
    ci_low: StrictFloat
    ci_high: StrictFloat
    evidence_type: Literal["public_synthetic"]


class JourneyRules(APIModel):
    rule_text: StrictStr
    observation_start: StrictStr
    observation_end: StrictStr


class JourneyResponse(APIModel):
    summaries: list[JourneySummary]
    survival: list[SurvivalRow]
    rules: JourneyRules
    evidence: Evidence
    limitations: list[StrictStr] = Field(min_length=1)
