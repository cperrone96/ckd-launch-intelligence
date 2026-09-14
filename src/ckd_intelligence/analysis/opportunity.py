"""Transparent, scenario-only opportunity scoring.

The public CKD source families do not share a defensible geographic grain: NHANES
and MEPS are survey populations, Part D is provider geography, and ClinicalTrials.gov
contains study-country mentions.  Consequently this module refuses to build a
geographic composite from raw source panels.  A caller must provide an explicitly
compatible, scenario-only aggregate for every component.  The output is a decision
scenario, never an observed market ranking or a patient-targeting recommendation.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

COMPONENTS: tuple[str, ...] = (
    "need",
    "screening_gap",
    "prescribing",
    "trial_activity",
)
_ALIASES = {"access": "screening_gap"}
_EVIDENCE_TYPES = {"public_observed", "public_synthetic", "fixture_only"}


@dataclass(frozen=True, slots=True)
class ComponentEvidence:
    """One aggregate input and its minimum provenance contract."""

    value: float | None
    source_population: str
    grain: str
    evidence_type: str
    provenance: str
    geography_scope: str
    time_period: str
    compatibility_key: str
    coverage: float
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SensitivityInterval:
    """Inclusive score/rank range across the supplied weight scenarios."""

    score_low: float | None
    score_high: float | None
    rank_low: int | None
    rank_high: int | None
    scenarios: int


@dataclass(frozen=True, slots=True)
class OpportunityRow:
    """A candidate scenario with traceable component values and score."""

    key: str
    geography: str
    time_period: str
    components: Mapping[str, float | None]
    normalized: Mapping[str, float | None]
    weights: Mapping[str, float]
    evidence: Mapping[str, ComponentEvidence]
    coverage: Mapping[str, float]
    score: float | None
    rank: int | None
    scorable: bool
    sensitivity: SensitivityInterval
    limitations: tuple[str, ...]

    @property
    def geography_scope(self) -> str:
        """Return the explicitly declared scenario geography scope."""

        scopes = {item.geography_scope for item in self.evidence.values()}
        return next(iter(scopes)) if len(scopes) == 1 else "mixed"


@dataclass(frozen=True, slots=True)
class OpportunityResult:
    """Ranking plus normalized component panels and sensitivity evidence."""

    rows: tuple[OpportunityRow, ...]
    components: Mapping[str, tuple[float | None, ...]]
    normalization: Mapping[str, Mapping[str, float | str]]
    weights: Mapping[str, float]
    sensitivity: Mapping[str, SensitivityInterval]
    minimum_coverage: float
    scenario_only: bool
    tie_policy: str = "score_desc_then_key_asc"

    @property
    def rankings(self) -> tuple[OpportunityRow, ...]:
        """Alias useful to API/dashboard consumers."""

        return self.rows

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation with provenance retained."""

        return {
            "scenario_only": self.scenario_only,
            "minimum_coverage": self.minimum_coverage,
            "tie_policy": self.tie_policy,
            "weights": dict(self.weights),
            "components": {key: list(values) for key, values in self.components.items()},
            "normalization": {key: dict(value) for key, value in self.normalization.items()},
            "sensitivity": {
                key: _sensitivity_dict(value) for key, value in self.sensitivity.items()
            },
            "rows": [_row_dict(row) for row in self.rows],
        }


def _sensitivity_dict(interval: SensitivityInterval) -> dict[str, int | float | None]:
    return {
        "score_low": interval.score_low,
        "score_high": interval.score_high,
        "rank_low": interval.rank_low,
        "rank_high": interval.rank_high,
        "scenarios": interval.scenarios,
    }


def _evidence_dict(evidence: ComponentEvidence) -> dict[str, Any]:
    return {
        "value": evidence.value,
        "source_population": evidence.source_population,
        "grain": evidence.grain,
        "evidence_type": evidence.evidence_type,
        "provenance": evidence.provenance,
        "geography_scope": evidence.geography_scope,
        "time_period": evidence.time_period,
        "compatibility_key": evidence.compatibility_key,
        "coverage": evidence.coverage,
        "limitations": list(evidence.limitations),
    }


def _row_dict(row: OpportunityRow) -> dict[str, Any]:
    return {
        "key": row.key,
        "geography": row.geography,
        "time_period": row.time_period,
        "components": dict(row.components),
        "normalized": dict(row.normalized),
        "weights": dict(row.weights),
        "evidence": {key: _evidence_dict(value) for key, value in row.evidence.items()},
        "coverage": dict(row.coverage),
        "score": row.score,
        "rank": row.rank,
        "scorable": row.scorable,
        "sensitivity": _sensitivity_dict(row.sensitivity),
        "limitations": list(row.limitations),
    }


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"opportunity input requires non-empty {field}")
    return value.strip()


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number or null")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number or null")
    return number


def _canonical_weights(weights: Mapping[str, float] | None) -> dict[str, float]:
    if weights is None:
        return {component: 1.0 / len(COMPONENTS) for component in COMPONENTS}
    if not isinstance(weights, Mapping) or not weights:
        raise ValueError("weights must be a non-empty mapping")
    total = sum(_number(value, f"weight {key}") for key, value in weights.items())
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError(f"weights must sum to 1 (got {total:g})")
    canonical: dict[str, float] = {}
    for raw_key, raw_value in weights.items():
        key = _ALIASES.get(raw_key, raw_key)
        if key not in COMPONENTS:
            raise ValueError(f"unknown opportunity component: {raw_key}")
        value = _number(raw_value, f"weight {raw_key}")
        if value < 0:
            raise ValueError("weights must be non-negative")
        if key in canonical:
            raise ValueError(f"duplicate opportunity component: {key}")
        canonical[key] = value
    missing = sorted(set(COMPONENTS) - set(canonical))
    if missing:
        raise ValueError(f"weights must declare every component: {', '.join(missing)}")
    return {component: canonical[component] for component in COMPONENTS}


def _component_name(raw: object) -> str:
    if not isinstance(raw, str):
        raise ValueError("component names must be text")
    name = _ALIASES.get(raw, raw)
    if name not in COMPONENTS:
        raise ValueError(f"unknown opportunity component: {raw}")
    return name


def _parse_evidence(
    raw: object,
    *,
    component: str,
    row: Mapping[str, Any],
    compatibility_key: str,
    time_period: str,
) -> ComponentEvidence:
    if isinstance(raw, Mapping):
        value = raw.get("value")
        source_population = raw.get("source_population")
        grain = raw.get("grain")
        evidence_type = raw.get("evidence_type")
        provenance = raw.get("provenance")
        geography_scope = raw.get("geography_scope")
        item_time = raw.get("time_period", time_period)
        item_key = raw.get("compatibility_key", compatibility_key)
        coverage = raw.get("coverage", 1.0)
        limitations = raw.get("limitations", ())
    else:
        value = raw
        # Scalar values are allowed only for explicit scenarios.  The generated
        # provenance says exactly what it is; it is not presented as source data.
        source_population = "caller-supplied illustrative scenario aggregate"
        grain = "scenario aggregate"
        evidence_type = "fixture_only"
        provenance = "caller-supplied fixture-only scenario input"
        geography_scope = "scenario"
        item_time = time_period
        item_key = compatibility_key
        coverage = 1.0
        limitations = ("Illustrative scenario input; not an observed geographic estimate.",)
    if value is not None:
        numeric_value: float | None = _number(value, f"{component} value")
    else:
        numeric_value = None
    source = _text(source_population, f"{component}.source_population")
    item_grain = _text(grain, f"{component}.grain")
    evidence = _text(evidence_type, f"{component}.evidence_type")
    if evidence not in _EVIDENCE_TYPES:
        raise ValueError(f"{component}.evidence_type is not a supported evidence type")
    item_provenance = _text(provenance, f"{component}.provenance")
    scope = _text(geography_scope, f"{component}.geography_scope")
    period = _text(item_time, f"{component}.time_period")
    key = _text(item_key, f"{component}.compatibility_key")
    coverage_value = _number(coverage, f"{component}.coverage")
    if not 0.0 <= coverage_value <= 1.0:
        raise ValueError(f"{component}.coverage must be between 0 and 1")
    if not isinstance(limitations, (list, tuple)):
        raise ValueError(f"{component}.limitations must be a sequence of text")
    limitation_values = tuple(_text(item, f"{component}.limitations") for item in limitations)
    if not limitation_values:
        raise ValueError(f"{component}.limitations must be non-empty")
    if evidence == "public_synthetic" and any(
        token in f"{source} {item_provenance}".lower()
        for token in ("caller", "illustrative", "notebook", "test")
    ):
        raise ValueError(
            f"{component} caller-created illustrative values must use fixture_only"
        )
    return ComponentEvidence(
        value=numeric_value,
        source_population=source,
        grain=item_grain,
        evidence_type=evidence,
        provenance=item_provenance,
        geography_scope=scope,
        time_period=period,
        compatibility_key=key,
        coverage=coverage_value,
        limitations=limitation_values,
    )


def _parse_row(
    raw: Mapping[str, Any], index: int
) -> tuple[str, str, str, dict[str, ComponentEvidence]]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"opportunity input {index} must be a mapping")
    scenario_only = raw.get("scenario_only")
    if scenario_only is not True:
        raise ValueError("composite opportunity ranks require scenario_only=True")
    key = _text(raw.get("key", raw.get("name", raw.get("geography"))), "key")
    geography = _text(raw.get("geography", key), "geography")
    time_period = _text(raw.get("time_period", raw.get("year")), "time_period")
    compatibility_key = _text(
        raw.get("compatibility_key", raw.get("comparison_key")), "compatibility_key"
    )
    raw_components = raw.get("components")
    if raw_components is None:
        raw_components = {component: raw.get(component) for component in COMPONENTS}
    if not isinstance(raw_components, Mapping):
        raise ValueError("components must be a mapping")
    names = {_component_name(name) for name in raw_components}
    missing = sorted(set(COMPONENTS) - names)
    if missing:
        raise ValueError(f"opportunity input is missing components: {', '.join(missing)}")
    evidence: dict[str, ComponentEvidence] = {}
    for raw_name, raw_value in raw_components.items():
        name = _component_name(raw_name)
        if name in evidence:
            raise ValueError(f"duplicate opportunity component: {name}")
        evidence[name] = _parse_evidence(
            raw_value,
            component=name,
            row=raw,
            compatibility_key=compatibility_key,
            time_period=time_period,
        )
    keys = {item.compatibility_key for item in evidence.values()}
    periods = {item.time_period for item in evidence.values()}
    scopes = {item.geography_scope for item in evidence.values()}
    if keys != {compatibility_key}:
        raise ValueError("opportunity components are not compatible: compatibility_key differs")
    if periods != {time_period}:
        raise ValueError("opportunity components have incompatible time periods")
    if len(scopes) != 1:
        raise ValueError("opportunity components are not compatible: geography scope differs")
    # A scenario scope is an explicit compatibility declaration.  National, state,
    # provider, or country source scopes are intentionally not silently equated.
    if next(iter(scopes)) != "scenario":
        raise ValueError(
            "opportunity components require geography_scope='scenario'; "
            "source-specific geography cannot be crosswalked implicitly"
        )
    return key, geography, time_period, evidence


def _normalization(
    evidence_rows: Sequence[dict[str, ComponentEvidence]],
    component: str,
    eligible_indices: set[int],
) -> tuple[dict[str, float | str], dict[int, float | None]]:
    available: list[float] = []
    for index in eligible_indices:
        value = evidence_rows[index][component].value
        if value is not None:
            available.append(value)
    if not available:
        return {
            "method": "min_max",
            "minimum": "null",
            "maximum": "null",
        }, {index: None for index in range(len(evidence_rows))}
    minimum = min(available)
    maximum = max(available)
    params: dict[str, float | str] = {
        "method": "min_max",
        "minimum": minimum,
        "maximum": maximum,
    }
    normalized: dict[int, float | None] = {}
    for index, row in enumerate(evidence_rows):
        if index not in eligible_indices:
            normalized[index] = None
            continue
        value = row[component].value
        if value is None:
            normalized[index] = None
        elif math.isclose(minimum, maximum, rel_tol=0.0, abs_tol=1e-15):
            normalized[index] = 0.5
        else:
            normalized[index] = (value - minimum) / (maximum - minimum)
    return params, normalized


def _rank_scores(scores: Mapping[str, float]) -> dict[str, int]:
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return {key: position for position, (key, _) in enumerate(ordered, start=1)}


def _score(
    normalized: Mapping[str, float | None], weights: Mapping[str, float]
) -> float | None:
    values: list[float] = []
    for component in COMPONENTS:
        value = normalized[component]
        if value is None:
            return None
        values.append(value)
    return sum(
        weights[component] * value
        for component, value in zip(COMPONENTS, values, strict=True)
    )


def rank_opportunities(
    inputs: Sequence[Mapping[str, Any]],
    weights: Mapping[str, float] | None = None,
    *,
    sensitivity_weights: Sequence[Mapping[str, float]] | None = None,
    minimum_coverage: float = 0.8,
) -> OpportunityResult:
    """Rank explicitly compatible scenario aggregates with sensitivity evidence.

    ``inputs`` must be scenario-only rows.  Each component carries source
    population, grain, evidence type, provenance, geography scope, time period,
    compatibility key, and coverage.  Missing values remain null and make a row
    unscorable; they are never imputed to zero.  Raw NHANES/MEPS/Part D/trial
    panels should be displayed separately, not passed directly to this function.
    Eligibility is resolved before component min/max fitting so incomplete rows
    cannot distort the scores of eligible candidates.
    """

    if not inputs:
        raise ValueError("inputs must contain at least one scenario row")
    minimum = _number(minimum_coverage, "minimum_coverage")
    if not 0.0 <= minimum <= 1.0:
        raise ValueError("minimum_coverage must be between 0 and 1")
    canonical = _canonical_weights(weights)
    parsed = [_parse_row(row, index) for index, row in enumerate(inputs)]
    keys = [row[0] for row in parsed]
    if len(set(keys)) != len(keys):
        raise ValueError("opportunity input keys must be unique")
    evidence_rows = [row[3] for row in parsed]
    candidate_keys = {
        evidence[component].compatibility_key
        for evidence in evidence_rows
        for component in COMPONENTS
    }
    if len(candidate_keys) != 1:
        raise ValueError(
            "candidates ranked together must share one exact compatible compatibility_key"
        )
    candidate_periods = {
        evidence[component].time_period
        for evidence in evidence_rows
        for component in COMPONENTS
    }
    if len(candidate_periods) != 1:
        raise ValueError("candidates ranked together must share one exact time period")
    coverage_rows = [
        {component: evidence[component].coverage for component in COMPONENTS}
        for evidence in evidence_rows
    ]
    eligible_indices = {
        index
        for index, evidence in enumerate(evidence_rows)
        if all(
            evidence[component].value is not None
            and coverage_rows[index][component] >= minimum
            for component in COMPONENTS
        )
    }
    normalization: dict[str, Mapping[str, float | str]] = {}
    normalized_by_component: dict[str, dict[int, float | None]] = {}
    for component in COMPONENTS:
        params, normalized = _normalization(evidence_rows, component, eligible_indices)
        normalization[component] = params
        normalized_by_component[component] = normalized
    normalized_rows: list[dict[str, float | None]] = [
        (
            {component: normalized_by_component[component][index] for component in COMPONENTS}
            if index in eligible_indices
            else {component: None for component in COMPONENTS}
        )
        for index in range(len(parsed))
    ]
    base_scores: dict[str, float] = {}
    for index, key in enumerate(keys):
        if index not in eligible_indices:
            continue
        score = _score(normalized_rows[index], canonical)
        if score is not None:
            base_scores[key] = score
    base_ranks = _rank_scores(base_scores)
    provided_sensitivity = list(sensitivity_weights or ())
    scenario_weights = [canonical, *(_canonical_weights(item) for item in provided_sensitivity)]
    scenario_scores: list[dict[str, float]] = []
    scenario_ranks: list[dict[str, int]] = []
    for scenario in scenario_weights:
        scores = {
            key: score
            for index, key in enumerate(keys)
            if key in base_scores
            for score in [_score(normalized_rows[index], scenario)]
            if score is not None
        }
        scenario_scores.append(scores)
        scenario_ranks.append(_rank_scores(scores))
    all_sensitivity: dict[str, SensitivityInterval] = {}
    for key in keys:
        key_scores = [mapping[key] for mapping in scenario_scores if key in mapping]
        ranks = [mapping[key] for mapping in scenario_ranks if key in mapping]
        all_sensitivity[key] = SensitivityInterval(
            score_low=min(key_scores) if key_scores else None,
            score_high=max(key_scores) if key_scores else None,
            rank_low=min(ranks) if ranks else None,
            rank_high=max(ranks) if ranks else None,
            scenarios=len(scenario_weights),
        )
    output_rows: list[OpportunityRow] = []
    for index, (key, geography, period, evidence) in enumerate(parsed):
        values = {component: evidence[component].value for component in COMPONENTS}
        coverage = coverage_rows[index]
        limitations = [
            limitation
            for component in COMPONENTS
            for limitation in evidence[component].limitations
        ]
        if any(value is None for value in values.values()):
            limitations.append("At least one component is missing; null was not treated as zero.")
        if any(value < minimum for value in coverage.values()):
            limitations.append(
                f"At least one component is below the {minimum:.0%} coverage threshold."
            )
        scorable = key in base_scores
        output_rows.append(
            OpportunityRow(
                key=key,
                geography=geography,
                time_period=period,
                components=values,
                normalized=normalized_rows[index],
                weights=canonical,
                evidence=evidence,
                coverage=coverage,
                score=base_scores.get(key),
                rank=base_ranks.get(key),
                scorable=scorable,
                sensitivity=all_sensitivity[key],
                limitations=tuple(dict.fromkeys(limitations)),
            )
        )
    output_rows.sort(key=lambda row: (row.rank is None, row.rank or math.inf, row.key))
    return OpportunityResult(
        rows=tuple(output_rows),
        components={
            component: tuple(evidence[component].value for evidence in evidence_rows)
            for component in COMPONENTS
        },
        normalization=normalization,
        weights=canonical,
        sensitivity=all_sensitivity,
        minimum_coverage=minimum,
        scenario_only=True,
    )
