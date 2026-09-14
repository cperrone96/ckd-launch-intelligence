from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ckd_intelligence.analysis.artifacts import (
    patient_finding_output_paths,
    patient_finding_source_provenance,
)
from ckd_intelligence.modeling.patient_finding import (
    CapacityBoundaryError,
    FeatureValidationError,
    LeakageError,
    LogisticScorer,
    _metric_intervals,
    _subgroup_metric_intervals,
    build_pre_lab_features,
    select_capacity_decision,
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


def test_fixture_provenance_identifies_and_hashes_actual_fixture_csv() -> None:
    provenance = patient_finding_source_provenance(Path("data"), "fixture_only")
    fixture = Path("data/fixtures/nhanes_patient_need_representative.csv")

    assert provenance["evidence_type"] == "fixture_only"
    assert provenance["path"] == fixture.as_posix()
    assert provenance["bytes"] == fixture.stat().st_size
    assert provenance["sha256"] == sha256(fixture.read_bytes()).hexdigest()
    assert "DEMO_J.xpt" not in json.dumps(provenance)


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
    assert artifact["selection_policy"] == "logistic_prespecified_before_holdout"
    assert artifact["source_provenance"]["path"] == (
        "data/manifests/nhanes-2017-2018-patient-need.json"
    )
    assert len(artifact["source_provenance"]["files"]) == 3
    sparse_age = next(
        row for row in artifact["subgroups"]["age_band"] if row["value"] == "18-39"
    )
    assert sparse_age["positives"] == 18
    assert sparse_age["precision_interval"] is None
    assert sparse_age["recall_interval"] is None
    assert sparse_age["brier_interval"] is None
    assert "sparse" in sparse_age["caveat"].casefold()
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


def test_development_capacity_uses_validation_predictions_and_respects_capacity() -> None:
    cohort, groups = _modeling_cohort()
    comparison = train_patient_finding_models(
        cohort, groups, capacity=0.12, bootstrap_replicates=20
    )

    decision = select_capacity_decision(comparison.selection_probabilities, capacity=0.12)

    assert decision.threshold == comparison.development_capacity.threshold
    assert sum(decision.selected) == decision.requested_count
    assert decision.selected_count == decision.requested_count
    assert decision.selected_share == pytest.approx(
        decision.requested_count / len(comparison.selection_probabilities)
    )
    assert decision.tie_policy == "descending_probability_then_stable_row_order"
    assert comparison.development_capacity.requested_count == decision.requested_count
    assert comparison.development_capacity.selected_count == decision.selected_count
    assert comparison.development_capacity.selected_share == decision.selected_share
    assert comparison.split.holdout_groups.isdisjoint(comparison.split.development_groups)
    assert comparison.split.threshold_source == "out_of_fold_development_predictions"


def test_comparison_reports_baselines_calibration_subgroups_and_denominators() -> None:
    cohort, groups = _modeling_cohort()

    comparison = train_patient_finding_models(
        cohort, groups, capacity=0.15, bootstrap_replicates=20
    )

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


def test_comparison_reports_cluster_aware_uncertainty_and_paired_differences() -> None:
    cohort, groups = _modeling_cohort()
    comparison = train_patient_finding_models(
        cohort,
        groups,
        capacity=0.15,
        bootstrap_replicates=80,
    )

    logistic = comparison.models["logistic_regression"]
    assert logistic.roc_auc_interval.method == "holdout_cluster_bootstrap_percentile"
    assert logistic.roc_auc_interval.cluster_count > 1
    assert logistic.roc_auc_interval.low <= logistic.roc_auc <= logistic.roc_auc_interval.high
    assert logistic.pr_auc_interval.low <= logistic.pr_auc <= logistic.pr_auc_interval.high
    assert logistic.brier_interval.low <= logistic.brier_score <= logistic.brier_interval.high
    paired = comparison.paired_differences["logistic_minus_random_forest_roc_auc"]
    assert paired.interval.low <= paired.estimate <= paired.interval.high
    assert paired.interval.valid_replicates > 0
    for dimension in ("age_band", "sex"):
        for metric in comparison.subgroups[dimension]:
            if metric.brier_interval is not None:
                assert metric.brier_interval.cluster_count > 1


def test_model_selection_is_prespecified_and_not_based_on_holdout_advantage() -> None:
    cohort, groups = _modeling_cohort()
    comparison = train_patient_finding_models(cohort, groups, bootstrap_replicates=20)

    assert comparison.selected_model == "logistic_regression"
    assert comparison.selection_policy == "logistic_prespecified_before_holdout"
    assert "holdout" not in comparison.selection_policy.replace("before_holdout", "")


def test_capacity_policy_never_exceeds_limit_when_probabilities_tie() -> None:
    decision = select_capacity_decision([0.8, 0.8, 0.8, 0.2], capacity=2)

    assert decision.selected == (True, True, False, False)
    assert decision.requested_count == 2
    assert decision.selected_count == 2
    assert decision.selected_share == 0.5
    assert decision.threshold == 0.8


def test_scalar_threshold_rejects_boundary_ties_that_cannot_encode_exact_capacity() -> None:
    cohort, groups = _modeling_cohort()
    comparison = train_patient_finding_models(
        cohort, groups, bootstrap_replicates=20
    )
    tied = replace(comparison, selection_probabilities=(0.8, 0.8, 0.8, 0.2))

    with pytest.raises(CapacityBoundaryError, match="select_capacity_decision"):
        select_operating_threshold(tied, capacity=2)


def test_cluster_bootstrap_reranks_capacity_inside_each_replicate() -> None:
    intervals = _metric_intervals(
        np.asarray([1, 0, 0, 1]),
        np.asarray([0.9, 0.8, 0.7, 0.1]),
        np.asarray(["A", "A", "B", "B"]),
        0.5,
        replicates=200,
        random_state=11,
    )

    precision = intervals["precision"]
    assert precision is not None
    assert precision.low == 0.0
    assert precision.high == 1.0


def test_subgroup_bootstrap_recomputes_exact_fractional_capacity_per_full_replicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ckd_intelligence.modeling import patient_finding

    observed: list[tuple[int, int, int]] = []
    original = patient_finding.select_capacity_decision

    def recording_decision(
        probabilities: list[float], capacity: float | int
    ) -> patient_finding.CapacityDecision:
        decision = original(probabilities, capacity)
        observed.append(
            (len(probabilities), decision.requested_count, decision.selected_count)
        )
        return decision

    monkeypatch.setattr(patient_finding, "select_capacity_decision", recording_decision)
    _subgroup_metric_intervals(
        np.asarray([1, 0, 0, 1, 0, 1, 0, 0, 1, 0]),
        np.linspace(0.95, 0.05, 10),
        np.asarray(["A", "A", "B", "B", "B", "C", "C", "C", "C", "C"]),
        np.asarray(["x", "y", "x", "y", "x", "y", "x", "y", "x", "y"]),
        "x",
        0.3,
        replicates=40,
        random_state=17,
    )

    assert len(observed) == 40
    assert len({total for total, _, _ in observed}) > 1
    assert all(requested == selected for _, requested, selected in observed)
    assert all(requested == max(1, round(total * 0.3)) for total, requested, _ in observed)


def test_training_and_json_artifact_are_deterministic() -> None:
    cohort, groups = _modeling_cohort()

    first = train_patient_finding_models(
        cohort, groups, capacity=0.15, bootstrap_replicates=20
    )
    second = train_patient_finding_models(
        cohort, groups, capacity=0.15, bootstrap_replicates=20
    )

    assert first.to_json() == second.to_json()
    assert "respondent_id" not in first.to_json()
    assert "survey_cluster" not in first.to_json()


def test_subgroup_with_no_capacity_flags_explains_undefined_precision() -> None:
    cohort, groups = _modeling_cohort()
    comparison = train_patient_finding_models(
        cohort, groups, capacity=0.01, bootstrap_replicates=20
    )

    unflagged = [
        metric
        for metrics in comparison.subgroups.values()
        for metric in metrics
        if metric.precision is None
    ]

    assert unflagged
    assert all(metric.caveat and "No records were flagged" in metric.caveat for metric in unflagged)


def test_one_cluster_subgroup_uncertainty_is_unavailable_with_caveat() -> None:
    cohort, groups = _modeling_cohort()
    initial = train_patient_finding_models(cohort, groups, bootstrap_replicates=20)
    rare_group = sorted(initial.split.holdout_groups)[0]
    cohort["age_years"] = 60
    cohort.loc[groups.astype(str).eq(rare_group), "age_years"] = 25

    comparison = train_patient_finding_models(cohort, groups, bootstrap_replicates=40)
    subgroup = next(
        metric for metric in comparison.subgroups["age_band"] if metric.value == "18-39"
    )

    assert subgroup.precision_interval is None
    assert subgroup.recall_interval is None
    assert subgroup.brier_interval is None
    assert subgroup.caveat is not None
    assert "fewer than two" in subgroup.caveat.casefold()


def test_scoring_artifact_rejects_incomplete_out_of_range_and_extra_input() -> None:
    cohort, groups = _modeling_cohort()
    comparison = train_patient_finding_models(
        cohort, groups, capacity=0.15, bootstrap_replicates=20
    )
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
    with pytest.raises(FeatureValidationError, match="JSON number"):
        scorer.score_one(
            {"age_years": "67", "sex": "Female", "race_ethnicity": "Group B"}
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
    comparison = train_patient_finding_models(
        cohort, groups, capacity=0.15, bootstrap_replicates=20
    )
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

    assert probabilities == pytest.approx(comparison.holdout_probabilities, abs=1e-12)


def test_portable_scorer_round_trip_is_validated_and_numerically_stable() -> None:
    cohort, groups = _modeling_cohort()
    comparison = train_patient_finding_models(cohort, groups, bootstrap_replicates=20)
    payload = json.loads(json.dumps(comparison.scorer.as_dict(), allow_nan=False))
    reloaded = LogisticScorer.from_dict(payload)
    row = {"age_years": 67, "sex": "Female", "race_ethnicity": "Group B"}

    assert reloaded.score_one(row) == pytest.approx(comparison.scorer.score_one(row), abs=1e-15)
    assert payload["artifact_version"] == "1.0.0"
    assert payload["missing_value_policy"] == "reject"
    assert payload["unknown_category_policy"] == "reject"
    assert payload["coefficient_precision"] == "float64"

    broken = dict(payload)
    broken["coefficients"] = broken["coefficients"][:-1]
    with pytest.raises(FeatureValidationError, match="coefficient length"):
        LogisticScorer.from_dict(broken)

    missing_scale = dict(payload)
    missing_scale["numeric_scales"] = {}
    with pytest.raises(FeatureValidationError, match="numeric preprocessing fields"):
        LogisticScorer.from_dict(missing_scale)

    numeric_string = dict(payload)
    numeric_string["coefficients"] = list(payload["coefficients"])
    numeric_string["coefficients"][0] = str(numeric_string["coefficients"][0])
    with pytest.raises(FeatureValidationError, match="JSON numbers"):
        LogisticScorer.from_dict(numeric_string)

    extreme = dict(payload)
    extreme["coefficients"] = [1e6] * len(extreme["coefficients"])
    extreme_scorer = LogisticScorer.from_dict(extreme)
    assert extreme_scorer.score_one(row) == 1.0


def test_threshold_selection_never_reads_holdout_probabilities() -> None:
    cohort, groups = _modeling_cohort()
    comparison = train_patient_finding_models(
        cohort, groups, capacity=0.15, bootstrap_replicates=20
    )
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


@pytest.mark.parametrize("target", ["age_years", "diabetes_history"])
def test_training_rejects_allowed_feature_as_target_and_invalid_training_input(
    target: str,
) -> None:
    cohort, groups = _modeling_cohort()
    with pytest.raises(LeakageError, match="fixed laboratory indicator"):
        train_patient_finding_models(cohort, groups, target_column=target)

    cohort.loc[0, "age_years"] = 121
    with pytest.raises(FeatureValidationError, match="age_years"):
        train_patient_finding_models(cohort, groups)


def test_training_rejects_grouped_folds_without_both_classes() -> None:
    cohort, _ = _modeling_cohort()
    cohort = cohort.iloc[:40].copy()
    cohort["ckd_indicator"] = 0
    cohort.loc[:3, "ckd_indicator"] = 1
    groups = pd.Series([f"group-{index // 4}" for index in range(40)])

    with pytest.raises(FeatureValidationError, match="fold.*both outcome classes"):
        train_patient_finding_models(cohort, groups)


def test_sensitivity_targets_must_use_the_same_complete_holdout_domain() -> None:
    cohort, groups = _modeling_cohort()
    cohort["sensitivity_egfr_only"] = cohort["ckd_indicator"]
    cohort.loc[0, "sensitivity_egfr_only"] = pd.NA

    with pytest.raises(FeatureValidationError, match="common complete-case domain"):
        train_patient_finding_models(cohort, groups)


def test_model_artifact_uses_strict_json_without_nan_tokens() -> None:
    cohort, groups = _modeling_cohort()
    comparison = train_patient_finding_models(cohort, groups, bootstrap_replicates=20)

    payload = json.dumps(comparison.to_artifact(), allow_nan=False)

    assert "NaN" not in payload
    assert "Infinity" not in payload
