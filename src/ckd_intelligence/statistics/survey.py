"""Design-based estimates for stratified, clustered public-use surveys.

All estimators use Taylor-series linearization with a with-replacement
approximation for primary sampling units (PSUs), as in R ``survey`` and Stata
``svy``. Domains (subpopulations) are estimated without subsetting the design:
every sampled row stays in the variance calculation, and rows outside the domain
contribute zero to the linearized totals. Rows outside every requested domain
may carry a zero weight (for example MEPS supplement weights), which keeps their
PSUs in the design.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from scipy.stats import t as student_t

LonelyPsuStrategy = Literal["error", "certainty"]

_DEFAULT_POPULATION = (
    "U.S. civilian, noninstitutionalized population represented by the source survey"
)


@dataclass(frozen=True, slots=True)
class Estimate:
    """A survey-weighted estimate with design metadata."""

    point: float
    standard_error: float
    ci_low: float
    ci_high: float
    confidence_level: float
    denominator: int
    design_observations: int
    excluded_missing: int
    sum_weights: float
    strata: int
    psus: int
    degrees_freedom: int
    variance_method: str
    lonely_psu_strategy: LonelyPsuStrategy
    source_population: str


@dataclass(frozen=True, slots=True)
class _Design:
    weight: np.ndarray
    stratum: np.ndarray
    cluster: np.ndarray


def _as_object_array(
    values: Sequence[object], name: str, expected: int | None = None
) -> np.ndarray:
    array = np.asarray(values, dtype=object)
    if array.ndim != 1 or (expected is not None and len(array) != expected):
        raise ValueError(f"{name} must be a one-dimensional sequence of matching length")
    return array


def _missing(value: object) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    if isinstance(value, (float, np.floating)):
        return bool(np.isnan(value))
    return False


def _design(
    n: int,
    weights: Sequence[float],
    strata: Sequence[object],
    psu: Sequence[object],
    *,
    confidence_level: float,
    lonely_psu: str,
) -> _Design:
    if n == 0:
        raise ValueError("survey inputs must not be empty")
    weight = np.asarray(weights, dtype=float)
    if weight.ndim != 1 or len(weight) != n:
        raise ValueError("weights must be a one-dimensional sequence of matching length")
    if not np.all(np.isfinite(weight)):
        raise ValueError("weights must be finite")
    if np.any(weight < 0):
        raise ValueError("weights must be nonnegative")
    stratum = _as_object_array(strata, "strata", n)
    cluster = _as_object_array(psu, "psu", n)
    if any(_missing(item) for item in stratum) or any(_missing(item) for item in cluster):
        raise ValueError("strata and PSU identifiers must not be missing")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be between zero and one")
    if lonely_psu not in {"error", "certainty"}:
        raise ValueError("lonely_psu must be 'error' or 'certainty'")
    return _Design(weight=weight, stratum=stratum, cluster=cluster)


def _domain_mask(domain: Sequence[bool] | None, n: int, name: str = "domain") -> np.ndarray:
    if domain is None:
        return np.ones(n, dtype=bool)
    raw_domain = _as_object_array(domain, name, n)
    if any(not isinstance(item, (bool, np.bool_)) for item in raw_domain):
        raise ValueError(f"{name} must contain only booleans")
    return raw_domain.astype(bool)


def _binary_outcome(outcome: np.ndarray, observed: np.ndarray) -> np.ndarray:
    numeric = np.zeros(len(outcome), dtype=float)
    for index in np.flatnonzero(observed):
        value = outcome[index]
        if isinstance(value, (bool, np.bool_)) or (
            isinstance(value, (int, float, np.integer, np.floating)) and float(value) in {0.0, 1.0}
        ):
            numeric[index] = float(value)
        else:
            raise ValueError("observed outcomes must be binary 0/1 values")
    return numeric


def _numeric_outcome(outcome: np.ndarray, observed: np.ndarray) -> np.ndarray:
    numeric = np.zeros(len(outcome), dtype=float)
    for index in np.flatnonzero(observed):
        value = outcome[index]
        if isinstance(value, (bool, np.bool_)):
            raise ValueError("observed outcomes must be numeric and not boolean")
        try:
            numeric[index] = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("observed outcomes must be numeric") from exc
        if not np.isfinite(numeric[index]):
            raise ValueError("observed outcomes must be finite")
    return numeric


def _domain_ratio(
    design: _Design, numeric: np.ndarray, analytic: np.ndarray
) -> tuple[float, float, np.ndarray]:
    """Return the domain mean, its weight total and per-row linearized values."""

    if not np.any(analytic):
        raise ValueError("domain has no observed outcomes")
    if np.any(design.weight[analytic] <= 0):
        raise ValueError("weights must be strictly positive for rows inside the domain")
    included_weight = design.weight * analytic
    sum_weights = float(included_weight.sum())
    point = float(np.dot(included_weight, numeric) / sum_weights)
    linearized = included_weight * (numeric - point) / sum_weights
    return point, sum_weights, linearized


def _taylor_variance(
    design: _Design, linearized: np.ndarray, lonely_psu: str
) -> tuple[float, int, int, int]:
    """Return variance, design degrees of freedom, stratum count and PSU count."""

    stratum_values = list(dict.fromkeys(design.stratum.tolist()))
    variance = 0.0
    degrees_freedom = 0
    unique_psus: set[tuple[object, object]] = set()
    lonely: list[object] = []
    for stratum_value in stratum_values:
        positions = np.flatnonzero(design.stratum == stratum_value)
        psu_values = list(dict.fromkeys(design.cluster[positions].tolist()))
        for psu_value in psu_values:
            unique_psus.add((stratum_value, psu_value))
        m_h = len(psu_values)
        if m_h < 2:
            lonely.append(stratum_value)
            continue
        totals = np.asarray(
            [
                linearized[
                    positions[np.asarray(design.cluster[positions] == psu_value, dtype=bool)]
                ].sum()
                for psu_value in psu_values
            ],
            dtype=float,
        )
        variance += float(m_h / (m_h - 1) * np.square(totals - totals.mean()).sum())
        degrees_freedom += m_h - 1
    if lonely and lonely_psu == "error":
        rendered = ", ".join(str(item) for item in lonely)
        raise ValueError(f"lonely PSU detected in strata: {rendered}")
    if degrees_freedom < 1:
        raise ValueError("survey design has no variance degrees of freedom")
    return variance, degrees_freedom, len(stratum_values), len(unique_psus)


def _critical_value(confidence_level: float, degrees_freedom: int) -> float:
    return float(student_t.ppf(0.5 + confidence_level / 2, degrees_freedom))


def weighted_prevalence(
    values: Sequence[object],
    weights: Sequence[float],
    strata: Sequence[object],
    psu: Sequence[object],
    *,
    domain: Sequence[bool] | None = None,
    confidence_level: float = 0.95,
    lonely_psu: LonelyPsuStrategy = "error",
    source_population: str = _DEFAULT_POPULATION,
) -> Estimate:
    """Estimate binary prevalence using weights and Taylor linearization.

    Missing outcomes are excluded from the analytic domain and never recoded to
    zero. Confidence limits use a Student-t critical value with survey design
    degrees of freedom (PSUs minus strata) and are clipped to [0, 1].
    """

    outcome = _as_object_array(values, "values")
    design = _design(
        len(outcome),
        weights,
        strata,
        psu,
        confidence_level=confidence_level,
        lonely_psu=lonely_psu,
    )
    domain_mask = _domain_mask(domain, len(outcome))
    observed = np.asarray([not _missing(item) for item in outcome], dtype=bool)
    analytic = domain_mask & observed
    numeric = _binary_outcome(outcome, observed)
    point, sum_weights, linearized = _domain_ratio(design, numeric, analytic)
    variance, degrees_freedom, strata_count, psu_count = _taylor_variance(
        design, linearized, lonely_psu
    )
    standard_error = float(np.sqrt(max(variance, 0.0)))
    critical = _critical_value(confidence_level, degrees_freedom)
    return Estimate(
        point=point,
        standard_error=standard_error,
        ci_low=max(0.0, point - critical * standard_error),
        ci_high=min(1.0, point + critical * standard_error),
        confidence_level=confidence_level,
        denominator=int(analytic.sum()),
        design_observations=len(outcome),
        excluded_missing=int((domain_mask & ~observed).sum()),
        sum_weights=sum_weights,
        strata=strata_count,
        psus=psu_count,
        degrees_freedom=degrees_freedom,
        variance_method="Taylor linearization for a stratified PSU ratio",
        lonely_psu_strategy=lonely_psu,
        source_population=source_population,
    )


def weighted_mean(
    values: Sequence[object],
    weights: Sequence[float],
    strata: Sequence[object],
    psu: Sequence[object],
    *,
    domain: Sequence[bool] | None = None,
    confidence_level: float = 0.95,
    lonely_psu: LonelyPsuStrategy = "error",
    source_population: str = _DEFAULT_POPULATION,
) -> Estimate:
    """Estimate a survey-weighted domain mean with Taylor linearization.

    Missing outcomes are excluded from the numerator and denominator. The returned
    ``Estimate`` uses the same metadata contract as ``weighted_prevalence``; its
    ``point`` and confidence limits are in the original outcome units.
    """

    outcome = _as_object_array(values, "values")
    design = _design(
        len(outcome),
        weights,
        strata,
        psu,
        confidence_level=confidence_level,
        lonely_psu=lonely_psu,
    )
    domain_mask = _domain_mask(domain, len(outcome))
    observed = np.asarray([not _missing(item) for item in outcome], dtype=bool)
    analytic = domain_mask & observed
    numeric = _numeric_outcome(outcome, observed)
    point, sum_weights, linearized = _domain_ratio(design, numeric, analytic)
    variance, degrees_freedom, strata_count, psu_count = _taylor_variance(
        design, linearized, lonely_psu
    )
    standard_error = float(np.sqrt(max(variance, 0.0)))
    critical = _critical_value(confidence_level, degrees_freedom)
    return Estimate(
        point=point,
        standard_error=standard_error,
        ci_low=point - critical * standard_error,
        ci_high=point + critical * standard_error,
        confidence_level=confidence_level,
        denominator=int(analytic.sum()),
        design_observations=len(outcome),
        excluded_missing=int((domain_mask & ~observed).sum()),
        sum_weights=sum_weights,
        strata=strata_count,
        psus=psu_count,
        degrees_freedom=degrees_freedom,
        variance_method="Taylor linearization for a stratified PSU weighted mean",
        lonely_psu_strategy=lonely_psu,
        source_population=source_population,
    )


def weighted_mean_difference(
    values: Sequence[object],
    weights: Sequence[float],
    strata: Sequence[object],
    psu: Sequence[object],
    *,
    domain: Sequence[bool],
    comparison_domain: Sequence[bool],
    confidence_level: float = 0.95,
    lonely_psu: LonelyPsuStrategy = "error",
    source_population: str = _DEFAULT_POPULATION,
) -> Estimate:
    """Estimate ``mean(domain) - mean(comparison_domain)`` with its design-based SE.

    Both domain means are linearized on the same full design, so the covariance
    between the two estimates (shared PSUs) is captured by differencing the
    per-row linearized values before PSU totals are formed. The domains must be
    disjoint. ``denominator`` and ``sum_weights`` describe both domains combined.
    """

    outcome = _as_object_array(values, "values")
    n = len(outcome)
    design = _design(
        n,
        weights,
        strata,
        psu,
        confidence_level=confidence_level,
        lonely_psu=lonely_psu,
    )
    first = _domain_mask(domain, n, "domain")
    second = _domain_mask(comparison_domain, n, "comparison_domain")
    if np.any(first & second):
        raise ValueError("domain and comparison_domain must be disjoint")
    observed = np.asarray([not _missing(item) for item in outcome], dtype=bool)
    numeric = _numeric_outcome(outcome, observed)
    first_point, first_weights, first_linearized = _domain_ratio(design, numeric, first & observed)
    second_point, second_weights, second_linearized = _domain_ratio(
        design, numeric, second & observed
    )
    variance, degrees_freedom, strata_count, psu_count = _taylor_variance(
        design, first_linearized - second_linearized, lonely_psu
    )
    point = first_point - second_point
    standard_error = float(np.sqrt(max(variance, 0.0)))
    critical = _critical_value(confidence_level, degrees_freedom)
    either = first | second
    return Estimate(
        point=point,
        standard_error=standard_error,
        ci_low=point - critical * standard_error,
        ci_high=point + critical * standard_error,
        confidence_level=confidence_level,
        denominator=int((either & observed).sum()),
        design_observations=n,
        excluded_missing=int((either & ~observed).sum()),
        sum_weights=first_weights + second_weights,
        strata=strata_count,
        psus=psu_count,
        degrees_freedom=degrees_freedom,
        variance_method="Taylor linearization for a difference of stratified PSU domain means",
        lonely_psu_strategy=lonely_psu,
        source_population=source_population,
    )
