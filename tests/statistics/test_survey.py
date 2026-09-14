from __future__ import annotations

import math

import pandas as pd
import pytest

from ckd_intelligence.statistics.survey import weighted_prevalence


def test_weighted_estimate_differs_from_unweighted_when_weights_differ() -> None:
    estimate = weighted_prevalence([1, 0], [9, 1], [1, 1], [1, 2])

    assert estimate.point == pytest.approx(0.9)
    assert estimate.denominator == 2
    assert estimate.sum_weights == pytest.approx(10.0)
    assert estimate.strata == 1
    assert estimate.psus == 2


def test_taylor_standard_error_uses_stratified_cluster_design() -> None:
    # Two strata with two PSUs each; every PSU contains one observation. Hand calculation:
    # p=.5, PSU linearized totals +/-0.125, stratum variance=.0625, total=.125.
    estimate = weighted_prevalence(
        [1, 0, 1, 0],
        [1, 1, 1, 1],
        [1, 1, 2, 2],
        [1, 2, 1, 2],
    )

    assert estimate.standard_error == pytest.approx(math.sqrt(0.125))
    assert estimate.degrees_freedom == 2
    assert estimate.ci_low == pytest.approx(0.0)
    assert estimate.ci_high == pytest.approx(1.0)
    assert estimate.variance_method == "Taylor linearization for a stratified PSU ratio"


def test_domain_estimate_preserves_full_sample_design_clusters() -> None:
    estimate = weighted_prevalence(
        [1, 0, 0, 1],
        [3, 1, 2, 2],
        [1, 1, 2, 2],
        [1, 2, 1, 2],
        domain=[True, True, False, True],
    )

    assert estimate.point == pytest.approx(5 / 6)
    assert estimate.denominator == 3
    assert estimate.design_observations == 4
    assert estimate.sum_weights == pytest.approx(6.0)


@pytest.mark.parametrize(
    ("weights", "strata", "psu", "message"),
    [
        ([1, 0], [1, 1], [1, 2], "weights"),
        ([1, float("inf")], [1, 1], [1, 2], "finite"),
        ([1, 1], [1, 2], [1, 1], "lonely PSU"),
    ],
)
def test_invalid_weights_or_design_fail_closed(
    weights: list[float], strata: list[int], psu: list[int], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        weighted_prevalence([1, 0], weights, strata, psu)


def test_missing_outcome_is_excluded_but_not_coerced_to_zero() -> None:
    estimate = weighted_prevalence(
        [1, pd.NA, 0, 1],
        [2, 5, 1, 1],
        [1, 1, 2, 2],
        [1, 2, 1, 2],
        lonely_psu="certainty",
    )

    assert estimate.point == pytest.approx(0.75)
    assert estimate.denominator == 3
    assert estimate.excluded_missing == 1
    assert estimate.sum_weights == pytest.approx(4.0)


def test_nonbinary_outcome_and_empty_domain_are_rejected() -> None:
    with pytest.raises(ValueError, match="binary"):
        weighted_prevalence([1, 2], [1, 1], [1, 1], [1, 2])
    with pytest.raises(ValueError, match="domain"):
        weighted_prevalence(
            [1, 0], [1, 1], [1, 1], [1, 2], domain=[False, False]
        )
