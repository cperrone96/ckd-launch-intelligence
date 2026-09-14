from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ckd_intelligence.analysis.artifacts import patient_finding_output_paths
from ckd_intelligence.modeling.patient_finding import (
    FeatureValidationError,
    LeakageError,
    build_pre_lab_features,
    select_operating_threshold,
    train_patient_finding_models,
)


def test_fixture_model_output_cannot_overwrite_official_model_artifact() -> None:
    official, official_checksum = patient_finding_output_paths(Path("data"), "public_observed")
    fixture, fixture_checksum = patient_finding_output_paths(Path("data"), "fixture_only")

    assert official == Path("data/processed/patient_finding_model_comparison.json")
    assert official_checksum == Path("data/processed/patient_finding_model_comparison.sha256")
    assert fixture == Path(
        "data/processed/fixture/patient_finding_model_comparison_fixture.json"
    )
    assert fixture_checksum == Path(
        "data/processed/fixture/patient_finding_model_comparison_fixture.sha256"
    )
    assert fixture != official


def test_official_model_artifact_is_aggregate_checksummed_and_nonclinical() -> None:
    artifact_path = Path("data/processed/patient_finding_model_comparison.json")
    checksum_path = Path("data/processed/patient_finding_model_comparison.sha256")
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))

    checksum_parts = checksum_path.read_text(encoding="utf-8").split()
    expected_digest = checksum_parts[0]
    assert sha256(artifact_path.read_bytes()).hexdigest() == expected_digest
    assert checksum_parts[1] == artifact_path.as_posix()
    assert artifact["evidence_type"] == "public_observed"
    assert artifact["split"]["threshold_source"] == "out_of_fold_development_predictions"
    assert "not a diagnosis" in artifact["intended_use"].casefold()
    assert artifact["features"] == ["age_years", "sex", "race_ethnicity"]
    payload = artifact_path.read_text(encoding="utf-8").casefold()
    assert "seqn" not in payload
    assert "respondent_id" not in payload


def _modeling_cohort() -> tuple[pd.DataFrame, pd.Series]:
    """Create a deterministic cohort with nontrivial signal and clustered groups."""

    rows: list[dict[str, object]] = []
    groups: list[str] = []
    races = ["Group A", "Group B", "Group C"]
    for group_number in range(36):
        for member in range(12):
            age = 18 + ((group_number * 7 + member * 5) % 68)
            sex = "Female" if (group_number + member) % 2 else "Male"
            race = races[(group_number + member) % len(races)]
            risk_points = (
                int(age >= 65) * 3
                + int(age >= 50)
                + int(sex == "Female")
                + int(race == "Group B")
                + int(member % 11 == 0)
            )
            rows.append(
                {
                    "age_years": age,
                    "sex": sex,
                    "race_ethnicity": race,
                    "ckd_indicator": int(risk_points >= 4),
                }
            )
            groups.append(f"stratum-{group_number // 2}-psu-{group_number % 2}")
    return pd.DataFrame(rows), pd.Series(groups, name="survey_cluster")


@pytest.mark.parametrize(
    "column",
    [
        "egfr",
        "estimated_egfr",
        "serum_creatinine_mg_dl",
        "log_creatinine",
        "urine_albumin_creatinine_ratio",
        "uacr_mg_g",
        "urine_albumin_mg_l",
        "urine_creatinine_mg_dl",
        "ckd_indicator",
        "derived_ckd_probability",
        "cystatin_c_mg_l",
        "blood_urea_nitrogen",
        "proteinuria_flag",
        "dialysis_history",
    ],
)
def test_outcome_defining_and_transformed_fields_are_rejected(column: str) -> None:
    frame = pd.DataFrame({column: [1.0], "age_years": [50]})

    with pytest.raises(LeakageError):
        build_pre_lab_features(frame, requested=[column])


def test_feature_builder_uses_only_documented_pre_lab_allowlist() -> None:
    frame = pd.DataFrame(
        {
            "age_years": [45, 70],
            "sex": ["Female", "Male"],
            "race_ethnicity": ["Group A", "Group B"],
            "sample_weight": [10.0, 20.0],
            "respondent_id": [100, 101],
        }
    )

    features = build_pre_lab_features(frame)

    assert list(features.columns) == ["age_years", "sex", "race_ethnicity"]
    assert "sample_weight" not in features
    assert "respondent_id" not in features
    with pytest.raises(FeatureValidationError, match="not in the pre-laboratory allowlist"):
        build_pre_lab_features(frame, requested=["sample_weight"])


def test_threshold_uses_validation_predictions_and_respects_capacity() -> None:
    cohort, groups = _modeling_cohort()
    comparison = train_patient_finding_models(cohort, groups, capacity=0.12)

    threshold = select_operating_threshold(comparison, capacity=0.12)
    selected = np.asarray(comparison.selection_probabilities) >= threshold

    assert selected.sum() == pytest.approx(0.12 * len(selected), abs=1)
    assert comparison.split.holdout_groups.isdisjoint(comparison.split.development_groups)
    assert comparison.split.threshold_source == "out_of_fold_development_predictions"


def test_comparison_reports_baselines_calibration_subgroups_and_denominators() -> None:
    cohort, groups = _modeling_cohort()

    comparison = train_patient_finding_models(cohort, groups, capacity=0.15)

    assert set(comparison.models) == {"prevalence_no_skill", "logistic_regression", "random_forest"}
    assert comparison.models["logistic_regression"].roc_auc > 0.5
    assert comparison.models["logistic_regression"].pr_auc > comparison.holdout_prevalence
    assert comparison.models["logistic_regression"].brier_score >= 0
    assert comparison.models["logistic_regression"].calibration_bins
    assert len(comparison.models["prevalence_no_skill"].calibration_bins) == 1
    assert set(comparison.subgroups) >= {"age_band", "sex"}
    assert comparison.holdout_n == sum(
        comparison.models["logistic_regression"].confusion_matrix.values()
    )
    assert "not a diagnosis" in comparison.intended_use.casefold()
    assert comparison.cohort_sensitivity
    for metrics in comparison.subgroups["age_band"]:
        if metrics.precision is None:
            assert metrics.caveat is not None


def test_training_and_json_artifact_are_deterministic() -> None:
    cohort, groups = _modeling_cohort()

    first = train_patient_finding_models(cohort, groups, capacity=0.15)
    second = train_patient_finding_models(cohort, groups, capacity=0.15)

    assert first.to_json() == second.to_json()
    assert "respondent_id" not in first.to_json()
    assert "survey_cluster" not in first.to_json()


def test_subgroup_with_no_capacity_flags_explains_undefined_precision() -> None:
    cohort, groups = _modeling_cohort()
    comparison = train_patient_finding_models(cohort, groups, capacity=0.01)

    unflagged = [
        metric
        for metrics in comparison.subgroups.values()
        for metric in metrics
        if metric.precision is None
    ]

    assert unflagged
    assert all(metric.caveat and "No records were flagged" in metric.caveat for metric in unflagged)


def test_scoring_artifact_rejects_incomplete_out_of_range_and_extra_input() -> None:
    cohort, groups = _modeling_cohort()
    comparison = train_patient_finding_models(cohort, groups, capacity=0.15)
    scorer = comparison.scorer

    probability = scorer.score_one(
        {"age_years": 67, "sex": "Female", "race_ethnicity": "Group B"}
    )

    assert 0 <= probability <= 1
    with pytest.raises(FeatureValidationError, match="missing required"):
        scorer.score_one({"age_years": 67, "sex": "Female"})
    with pytest.raises(FeatureValidationError, match="age_years"):
        scorer.score_one(
            {"age_years": 121, "sex": "Female", "race_ethnicity": "Group B"}
        )
    with pytest.raises(LeakageError):
        scorer.score_one(
            {
                "age_years": 67,
                "sex": "Female",
                "race_ethnicity": "Group B",
                "egfr": 42,
            }
        )


def test_portable_json_scorer_reproduces_fitted_logistic_holdout_probabilities() -> None:
    cohort, groups = _modeling_cohort()
    comparison = train_patient_finding_models(cohort, groups, capacity=0.15)
    holdout = cohort.loc[groups.astype(str).isin(comparison.split.holdout_groups)]

    probabilities = [
        comparison.scorer.score_one(
            {
                "age_years": row.age_years,
                "sex": row.sex,
                "race_ethnicity": row.race_ethnicity,
            }
        )
        for row in holdout.itertuples(index=False)
    ]

    assert np.mean(probabilities) == pytest.approx(
        comparison.models["logistic_regression"].mean_probability,
        abs=1e-12,
    )


def test_threshold_selection_never_reads_holdout_probabilities() -> None:
    cohort, groups = _modeling_cohort()
    comparison = train_patient_finding_models(cohort, groups, capacity=0.15)
    original = select_operating_threshold(comparison, capacity=0.20)
    tampered_metrics = replace(
        comparison.models["logistic_regression"],
        mean_probability=0.999,
    )
    tampered = replace(
        comparison,
        models={**comparison.models, "logistic_regression": tampered_metrics},
    )

    assert select_operating_threshold(tampered, capacity=0.20) == original


def test_training_rejects_fractional_target_values_instead_of_truncating_them() -> None:
    cohort, groups = _modeling_cohort()
    cohort["ckd_indicator"] = cohort["ckd_indicator"].astype(float)
    cohort.loc[0, "ckd_indicator"] = 0.5

    with pytest.raises(FeatureValidationError, match="complete and binary"):
        train_patient_finding_models(cohort, groups)
