"""Design-based estimates for stratified, clustered public-use surveys."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from scipy.stats import t as student_t

LonelyPsuStrategy = Literal["error", "certainty"]


@dataclass(frozen=True, slots=True)
class Estimate:
    """A survey-weighted prevalence estimate with design metadata."""

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


def weighted_prevalence(
    values: Sequence[object],
    weights: Sequence[float],
    strata: Sequence[object],
    psu: Sequence[object],
    *,
    domain: Sequence[bool] | None = None,
    confidence_level: float = 0.95,
    lonely_psu: LonelyPsuStrategy = "error",
    source_population: str = (
        "U.S. civilian, noninstitutionalized population represented by the source survey"
    ),
) -> Estimate:
    """Estimate binary prevalence using weights and Taylor linearization.

    Domains are estimated as subpopulations: all sampled rows remain in the
    variance design while out-of-domain rows contribute zero to the ratio
    linearization. Missing outcomes are excluded from the analytic domain and
    never recoded to zero. Confidence limits use a Student-t critical value with
    survey design degrees of freedom and are clipped to the parameter space.
    """

    outcome = _as_object_array(values, "values")
    n = len(outcome)
    if n == 0:
        raise ValueError("survey inputs must not be empty")
    weight = np.asarray(weights, dtype=float)
    if weight.ndim != 1 or len(weight) != n:
        raise ValueError("weights must be a one-dimensional sequence of matching length")
    if not np.all(np.isfinite(weight)):
        raise ValueError("weights must be finite")
    if np.any(weight <= 0):
        raise ValueError("weights must be strictly positive")
    stratum = _as_object_array(strata, "strata", n)
    cluster = _as_object_array(psu, "psu", n)
    if any(_missing(item) for item in stratum) or any(_missing(item) for item in cluster):
        raise ValueError("strata and PSU identifiers must not be missing")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be between zero and one")
    if lonely_psu not in {"error", "certainty"}:
        raise ValueError("lonely_psu must be 'error' or 'certainty'")

    domain_mask = np.ones(n, dtype=bool)
    if domain is not None:
        raw_domain = _as_object_array(domain, "domain", n)
        if any(not isinstance(item, (bool, np.bool_)) for item in raw_domain):
            raise ValueError("domain must contain only booleans")
        domain_mask = raw_domain.astype(bool)
    observed = np.asarray([not _missing(item) for item in outcome], dtype=bool)
    analytic = domain_mask & observed
    if not np.any(analytic):
        raise ValueError("domain has no observed outcomes")

    numeric_outcome = np.zeros(n, dtype=float)
    for index in np.flatnonzero(observed):
        value = outcome[index]
        if isinstance(value, (bool, np.bool_)) or (
            isinstance(value, (int, float, np.integer, np.floating)) and float(value) in {0.0, 1.0}
        ):
            numeric_outcome[index] = float(value)
        else:
            raise ValueError("observed outcomes must be binary 0/1 values")

    included_weight = weight * analytic
    sum_weights = float(included_weight.sum())
    if sum_weights <= 0:
        raise ValueError("domain must have positive total weight")
    point = float(np.dot(included_weight, numeric_outcome) / sum_weights)
    linearized = included_weight * (numeric_outcome - point) / sum_weights

    stratum_values = list(dict.fromkeys(stratum.tolist()))
    variance = 0.0
    degrees_freedom = 0
    unique_psus: set[tuple[object, object]] = set()
    lonely: list[object] = []
    for stratum_value in stratum_values:
        positions = np.flatnonzero(stratum == stratum_value)
        psu_values = list(dict.fromkeys(cluster[positions].tolist()))
        for psu_value in psu_values:
            unique_psus.add((stratum_value, psu_value))
        m_h = len(psu_values)
        if m_h < 2:
            lonely.append(stratum_value)
            continue
        totals = np.asarray(
            [
                linearized[positions[np.asarray(cluster[positions] == psu_value, dtype=bool)]].sum()
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

    standard_error = float(np.sqrt(max(variance, 0.0)))
    critical = float(student_t.ppf(0.5 + confidence_level / 2, degrees_freedom))
    return Estimate(
        point=point,
        standard_error=standard_error,
        ci_low=max(0.0, point - critical * standard_error),
        ci_high=min(1.0, point + critical * standard_error),
        confidence_level=confidence_level,
        denominator=int(analytic.sum()),
        design_observations=n,
        excluded_missing=int((domain_mask & ~observed).sum()),
        sum_weights=sum_weights,
        strata=len(stratum_values),
        psus=len(unique_psus),
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
    source_population: str = (
        "U.S. civilian, noninstitutionalized population represented by the source survey"
    ),
) -> Estimate:
    """Estimate a survey-weighted mean with Taylor linearization and a domain.

    Missing outcomes are excluded from the numerator and denominator. Rows outside
    the requested domain remain in the design for variance estimation. The returned
    ``Estimate`` uses the same metadata contract as ``weighted_prevalence``; its
    ``point`` and confidence limits are in the original outcome units.
    """

    outcome = _as_object_array(values, "values")
    n = len(outcome)
    if n == 0:
        raise ValueError("survey inputs must not be empty")
    weight = np.asarray(weights, dtype=float)
    if weight.ndim != 1 or len(weight) != n:
        raise ValueError("weights must be a one-dimensional sequence of matching length")
    if not np.all(np.isfinite(weight)):
        raise ValueError("weights must be finite")
    if np.any(weight <= 0):
        raise ValueError("weights must be strictly positive")
    stratum = _as_object_array(strata, "strata", n)
    cluster = _as_object_array(psu, "psu", n)
    if any(_missing(item) for item in stratum) or any(_missing(item) for item in cluster):
        raise ValueError("strata and PSU identifiers must not be missing")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be between zero and one")
    if lonely_psu not in {"error", "certainty"}:
        raise ValueError("lonely_psu must be 'error' or 'certainty'")

    domain_mask = np.ones(n, dtype=bool)
    if domain is not None:
        raw_domain = _as_object_array(domain, "domain", n)
        if any(not isinstance(item, (bool, np.bool_)) for item in raw_domain):
            raise ValueError("domain must contain only booleans")
        domain_mask = raw_domain.astype(bool)
    observed = np.asarray([not _missing(item) for item in outcome], dtype=bool)
    analytic = domain_mask & observed
    if not np.any(analytic):
        raise ValueError("domain has no observed outcomes")

    numeric = np.zeros(n, dtype=float)
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

    included_weight = weight * analytic
    sum_weights = float(included_weight.sum())
    if sum_weights <= 0:
        raise ValueError("domain must have positive total weight")
    point = float(np.dot(included_weight, numeric) / sum_weights)
    linearized = included_weight * (numeric - point) / sum_weights

    stratum_values = list(dict.fromkeys(stratum.tolist()))
    variance = 0.0
    degrees_freedom = 0
    unique_psus: set[tuple[object, object]] = set()
    lonely: list[object] = []
    for stratum_value in stratum_values:
        positions = np.flatnonzero(stratum == stratum_value)
        psu_values = list(dict.fromkeys(cluster[positions].tolist()))
        for psu_value in psu_values:
            unique_psus.add((stratum_value, psu_value))
        if len(psu_values) < 2:
            lonely.append(stratum_value)
            continue
        totals = np.asarray(
            [
                linearized[positions[np.asarray(cluster[positions] == psu_value, dtype=bool)]].sum()
                for psu_value in psu_values
            ],
            dtype=float,
        )
        variance += float(
            len(psu_values) / (len(psu_values) - 1) * np.square(totals - totals.mean()).sum()
        )
        degrees_freedom += len(psu_values) - 1
    if lonely and lonely_psu == "error":
        rendered = ", ".join(str(item) for item in lonely)
        raise ValueError(f"lonely PSU detected in strata: {rendered}")
    if degrees_freedom < 1:
        raise ValueError("survey design has no variance degrees of freedom")

    standard_error = float(np.sqrt(max(variance, 0.0)))
    critical = float(student_t.ppf(0.5 + confidence_level / 2, degrees_freedom))
    return Estimate(
        point=point,
        standard_error=standard_error,
        ci_low=point - critical * standard_error,
        ci_high=point + critical * standard_error,
        confidence_level=confidence_level,
        denominator=int(analytic.sum()),
        design_observations=n,
        excluded_missing=int((domain_mask & ~observed).sum()),
        sum_weights=sum_weights,
        strata=len(stratum_values),
        psus=len(unique_psus),
        degrees_freedom=degrees_freedom,
        variance_method="Taylor linearization for a stratified PSU weighted mean",
        lonely_psu_strategy=lonely_psu,
        source_population=source_population,
    )
