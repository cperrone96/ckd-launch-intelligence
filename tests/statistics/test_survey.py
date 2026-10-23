from __future__ import annotations

import math

import pandas as pd
import pytest

from ckd_intelligence.statistics.survey import (
    weighted_mean,
    weighted_mean_difference,
    weighted_prevalence,
)


def test_weighted_estimate_differs_from_unweighted_when_weights_differ() -> None:
    estimate = weighted_prevalence([1, 0], [9, 1], [1, 1], [1, 2])

    assert estimate.point == pytest.approx(0.9)
    assert estimate.denominator == 2
    assert estimate.sum_weights == pytest.approx(10.0)
    assert estimate.strata == 1
    assert estimate.psus == 2


def test_weighted_mean_preserves_units_and_design_metadata() -> None:
    estimate = weighted_mean(
        [10.0, 20.0, 30.0, 40.0],
        [1.0, 2.0, 3.0, 4.0],
        [1, 1, 2, 2],
        [1, 2, 1, 2],
        source_population="MEPS proxy domain",
    )
    assert estimate.point == pytest.approx(30.0)
    assert estimate.denominator == 4
    assert estimate.source_population == "MEPS proxy domain"
    assert estimate.variance_method.startswith("Taylor")


def test_weighted_mean_excludes_missing_outcome_without_recoding_to_zero() -> None:
    estimate = weighted_mean(
        [10.0, None, 30.0, 40.0],
        [1.0, 2.0, 3.0, 4.0],
        [1, 1, 2, 2],
        [1, 2, 1, 2],
        lonely_psu="certainty",
    )
    assert estimate.point == pytest.approx(32.5)
    assert estimate.denominator == 3
    assert estimate.excluded_missing == 1


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
        weighted_prevalence([1, 0], [1, 1], [1, 1], [1, 2], domain=[False, False])


def test_excluded_missing_counts_only_missing_outcomes_inside_domain() -> None:
    estimate = weighted_prevalence(
        [pd.NA, pd.NA, 1, 0],
        [1, 1, 1, 1],
        [1, 1, 2, 2],
        [1, 2, 1, 2],
        domain=[False, True, True, True],
    )

    assert estimate.denominator == 2
    assert estimate.excluded_missing == 1


def test_zero_weight_rows_outside_domain_keep_their_psus_in_the_design() -> None:
    # Stratum 2 has one PSU with domain members and one PSU with only zero-weight,
    # out-of-domain rows. Subsetting would leave stratum 2 with a lonely PSU and drop
    # its variance contribution; the domain estimator keeps the PSU with a zero total.
    values = [10.0, 20.0, 30.0, 99.0]
    weights = [1.0, 1.0, 2.0, 0.0]
    strata = [1, 1, 2, 2]
    psu = [1, 2, 1, 2]
    domain = [True, True, True, False]

    full = weighted_mean(values, weights, strata, psu, domain=domain)
    subset = weighted_mean(values[:3], weights[:3], strata[:3], psu[:3], lonely_psu="certainty")

    assert full.point == pytest.approx(subset.point) == pytest.approx(22.5)
    assert full.degrees_freedom == 2
    assert subset.degrees_freedom == 1
    assert full.standard_error > subset.standard_error


def test_zero_weight_inside_domain_is_rejected() -> None:
    with pytest.raises(ValueError, match="strictly positive"):
        weighted_mean([1.0, 2.0], [1.0, 0.0], [1, 1], [1, 2])
    with pytest.raises(ValueError, match="nonnegative"):
        weighted_mean([1.0, 2.0], [1.0, -1.0], [1, 1], [1, 2])


def test_domain_difference_matches_component_means_and_shared_psu_covariance() -> None:
    values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0]
    weights = [1.0, 2.0, 1.0, 2.0, 1.0, 2.0, 1.0, 2.0]
    strata = [1, 1, 1, 1, 2, 2, 2, 2]
    psu = [1, 1, 2, 2, 1, 1, 2, 2]
    first = [True, False, True, False, True, False, True, False]
    second = [not item for item in first]

    difference = weighted_mean_difference(
        values, weights, strata, psu, domain=first, comparison_domain=second
    )
    mean_first = weighted_mean(values, weights, strata, psu, domain=first)
    mean_second = weighted_mean(values, weights, strata, psu, domain=second)

    assert difference.point == pytest.approx(mean_first.point - mean_second.point)
    assert difference.denominator == 8
    # Within every PSU the two domains differ by exactly 10, so the shared-PSU covariance
    # cancels all between-PSU variation. Treating the means as independent would not.
    independent_se = math.sqrt(mean_first.standard_error**2 + mean_second.standard_error**2)
    assert independent_se > 1.0
    assert difference.standard_error == pytest.approx(0.0, abs=1e-9)


def test_domain_difference_requires_disjoint_domains() -> None:
    with pytest.raises(ValueError, match="disjoint"):
        weighted_mean_difference(
            [1.0, 2.0],
            [1.0, 1.0],
            [1, 1],
            [1, 2],
            domain=[True, True],
            comparison_domain=[True, False],
        )
