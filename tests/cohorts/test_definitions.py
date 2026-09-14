from __future__ import annotations

import pandas as pd
import pytest

from ckd_intelligence.cohorts.definitions import (
    CKDDefinition,
    calculate_egfr_ckd_epi_2021,
    classify_ckd,
)


def test_ckd_indicator_uses_documented_egfr_or_albuminuria_rule() -> None:
    # A low eGFR, high UACR, neither, and neither respectively.
    people = pd.DataFrame(
        {
            "age_years": [75, 40, 30, 50],
            "sex": ["Female", "Male", "Female", "Male"],
            "serum_creatinine_mg_dl": [1.8, 0.8, 0.7, 0.9],
            "urine_albumin_mg_l": [5.0, 45.0, 5.0, 10.0],
            "urine_creatinine_mg_dl": [100.0, 100.0, 100.0, 100.0],
        }
    )

    result = classify_ckd(people, CKDDefinition.primary())

    assert result.tolist() == [True, True, False, False]
    assert str(result.dtype) == "boolean"


@pytest.mark.parametrize(
    ("age", "sex", "creatinine", "expected"),
    [
        (50, "Female", 1.0, 68.633),
        (50, "Male", 1.0, 91.691),
    ],
)
def test_egfr_matches_hand_calculated_2021_ckd_epi_values(
    age: int, sex: str, creatinine: float, expected: float
) -> None:
    result = calculate_egfr_ckd_epi_2021(
        pd.Series([creatinine]), pd.Series([age]), pd.Series([sex])
    )

    assert result.iloc[0] == pytest.approx(expected, abs=0.001)


def test_missing_primary_defining_labs_remain_unknown_and_are_never_false() -> None:
    people = pd.DataFrame(
        {
            "age_years": [60, 60, 60, 60],
            "sex": ["Female"] * 4,
            "serum_creatinine_mg_dl": [pd.NA, pd.NA, 0.8, 2.0],
            "urine_albumin_mg_l": [pd.NA, 40.0, pd.NA, pd.NA],
            "urine_creatinine_mg_dl": [pd.NA, 100.0, pd.NA, pd.NA],
        }
    )

    result = classify_ckd(people, CKDDefinition.primary())

    assert result.isna().tolist() == [True, True, True, True]


def test_people_outside_documented_adult_domain_are_unknown() -> None:
    person = pd.DataFrame(
        {
            "age_years": [17],
            "sex": ["Male"],
            "serum_creatinine_mg_dl": [2.0],
            "urine_albumin_mg_l": [100.0],
            "urine_creatinine_mg_dl": [100.0],
        }
    )

    result = classify_ckd(person, CKDDefinition.primary())

    assert result.isna().item()


def test_egfr_only_sensitivity_does_not_treat_missing_egfr_as_negative() -> None:
    person = pd.DataFrame(
        {
            "age_years": [55],
            "sex": ["Female"],
            "serum_creatinine_mg_dl": [pd.NA],
            "urine_albumin_mg_l": [80.0],
            "urine_creatinine_mg_dl": [100.0],
        }
    )

    result = classify_ckd(person, CKDDefinition.egfr_only())

    assert result.isna().item()


def test_classification_rejects_unsupported_sex_code() -> None:
    person = pd.DataFrame(
        {
            "age_years": [55],
            "sex": ["Unknown"],
            "serum_creatinine_mg_dl": [1.0],
            "urine_albumin_mg_l": [5.0],
            "urine_creatinine_mg_dl": [100.0],
        }
    )

    with pytest.raises(ValueError, match="sex"):
        classify_ckd(person, CKDDefinition.primary())


def test_missing_sex_needed_for_egfr_produces_unknown() -> None:
    person = pd.DataFrame(
        {
            "age_years": [55],
            "sex": [pd.NA],
            "serum_creatinine_mg_dl": [1.0],
            "urine_albumin_mg_l": [5.0],
            "urine_creatinine_mg_dl": [100.0],
        }
    )

    result = classify_ckd(person, CKDDefinition.primary())

    assert result.isna().item()


def test_known_pregnancy_is_excluded_but_negative_unknown_and_not_applicable_are_kept() -> None:
    people = pd.DataFrame(
        {
            "age_years": [30, 30, 30, 30],
            "sex": ["Female", "Female", "Female", "Male"],
            "pregnancy_status_code": [1, 2, 3, pd.NA],
            "serum_creatinine_mg_dl": [0.8] * 4,
            "urine_albumin_mg_l": [5.0] * 4,
            "urine_creatinine_mg_dl": [100.0] * 4,
        }
    )

    result = classify_ckd(people, CKDDefinition.primary())

    assert result.isna().tolist() == [True, False, False, False]


def test_official_uacr_is_preferred_over_recalculation() -> None:
    person = pd.DataFrame(
        {
            "age_years": [50],
            "sex": ["Male"],
            "serum_creatinine_mg_dl": [0.9],
            "urine_albumin_mg_l": [40.0],
            "urine_creatinine_mg_dl": [100.0],
            "uacr_mg_g": [29.0],
        }
    )

    result = classify_ckd(person, CKDDefinition.primary())

    assert result.tolist() == [False]


def test_recalculated_uacr_exact_threshold_is_positive() -> None:
    person = pd.DataFrame(
        {
            "age_years": [50],
            "sex": ["Male"],
            "serum_creatinine_mg_dl": [0.9],
            "urine_albumin_mg_l": [10.2],
            "urine_creatinine_mg_dl": [34.0],
        }
    )

    result = classify_ckd(person, CKDDefinition.primary())

    assert result.tolist() == [True]


def test_missing_official_uacr_uses_component_fallback() -> None:
    person = pd.DataFrame(
        {
            "age_years": [50],
            "sex": ["Male"],
            "serum_creatinine_mg_dl": [0.9],
            "urine_albumin_mg_l": [10.2],
            "urine_creatinine_mg_dl": [34.0],
            "uacr_mg_g": [pd.NA],
        }
    )

    result = classify_ckd(person, CKDDefinition.primary())

    assert result.tolist() == [True]
