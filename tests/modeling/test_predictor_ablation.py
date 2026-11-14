from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pandas as pd

from ckd_intelligence.analysis import predictor_ablation as ablation
from ckd_intelligence.analysis.nhanes_pipeline import LoadedPeople, ModelingCohort
from ckd_intelligence.cohorts.definitions import CKDDefinition
from ckd_intelligence.modeling.patient_finding import (
    ALLOWED_FEATURES,
    POINT_OF_CARE_LAB_FEATURES,
    QUESTIONNAIRE_ABLATION_FEATURES,
)

EGFR = CKDDefinition.egfr_only().name
ALBUMINURIA = CKDDefinition.albuminuria_only().name
PRIMARY = CKDDefinition.primary().name


def _people(n_groups: int = 36, members: int = 12) -> pd.DataFrame:
    """Deterministic participants with every ablation predictor and nontrivial signal."""

    rows: list[dict[str, object]] = []
    for g in range(n_groups):
        for m in range(members):
            i = g * members + m
            age = 18 + ((g * 7 + m * 5) % 68)
            hba1c = 5.0 + ((g + 3 * m) % 9) * 0.5
            risk = int(age >= 65) * 3 + int(age >= 50) + int(hba1c >= 7.0) + int(m % 11 == 0)
            positive = int(risk >= 4)
            low_egfr = positive and m % 3 == 0
            albuminuria = positive and not low_egfr or (positive and m % 2 == 0)
            row: dict[str, object] = {
                "respondent_id": float(1000 + i),
                "age_years": age,
                "sex": "Female" if (g + m) % 2 else "Male",
                "race_ethnicity": ["Group A", "Group B", "Group C"][(g + m) % 3],
                "body_mass_index": 22.0 + (i % 15),
                "systolic_blood_pressure": 105.0 + (i % 50),
                "diabetes_history": "Yes" if hba1c >= 7.0 else "No",
                "hypertension_history": "Yes" if m % 2 else "No",
                "smoking_status": ["Never", "Former", "Current"][m % 3],
                "pregnancy_status_code": None,
                PRIMARY: positive,
                EGFR: int(low_egfr),
                ALBUMINURIA: int(albuminuria),
                "strata": float(g // 2),
                "psu": float(g % 2 + 1),
            }
            rows.append(row)
    return pd.DataFrame(rows)


def _extra(people: pd.DataFrame) -> pd.DataFrame:
    """All 22 ablation predictors, two levels per category so every fold sees both."""

    i = pd.Series(range(len(people)))
    extra = pd.DataFrame({"respondent_id": people["respondent_id"]})
    extra["hba1c_percent"] = 5.0 + ((i // 12 + 3 * (i % 12)) % 9) * 0.5
    extra["hemoglobin_g_dl"] = 12.0 + (i % 7) * 0.4
    extra["waist_cm"] = 80.0 + (i % 30)
    extra["diastolic_blood_pressure"] = 65.0 + (i % 20)
    for name in QUESTIONNAIRE_ABLATION_FEATURES:
        if name not in extra:
            extra[name] = (i % 2).map({0: "No", 1: "Yes"})
    return extra


def _loaded(people: pd.DataFrame) -> LoadedPeople:
    return LoadedPeople(
        people=people,
        source_participant_count=len(people),
        evidence_type="public_observed",
        manifest={},
    )


def test_ablation_cohort_drops_incomplete_rows_and_reports_them() -> None:
    people = _people()
    extra = _extra(people)
    extra.loc[[0, 1, 2], "stroke_history"] = pd.NA
    extra.loc[[3], "hba1c_percent"] = float("nan")

    cohort = ablation.ablation_cohort(_loaded(people), extra)

    assert len(cohort.frame) == len(people) - 4
    assert set(ALLOWED_FEATURES).issubset(cohort.frame.columns)
    missing = cohort.attrition["missing_by_predictor"]
    assert isinstance(missing, dict)
    assert missing["stroke_history"] == 3 and missing["hba1c_percent"] == 1


def _cohort() -> ModelingCohort:
    people = _people()
    return ablation.ablation_cohort(_loaded(people), _extra(people))


def test_every_feature_set_is_scored_on_the_same_people() -> None:
    result = ablation.run_ablation(_cohort(), bootstrap_replicates=20, nested_selection=False)

    assert set(result["feature_sets"]) == set(ablation.FEATURE_SETS)
    assert {s["evaluated_n"] for s in result["feature_sets"].values()} == {result["evaluated_n"]}
    assert set(result["paired_vs_current"]) == {
        "plus_questionnaire",
        "plus_point_of_care_labs",
        "plus_labs_and_questionnaire",
    }
    labs = result["feature_sets"]["plus_point_of_care_labs"]
    assert labs["features"][-2:] == list(POINT_OF_CARE_LAB_FEATURES)
    roc = result["paired_vs_current"]["plus_point_of_care_labs"]["roc_auc"]
    assert roc["comparison"] == "plus_point_of_care_labs minus current_pre_lab"


def test_target_coverage_counts_add_up_to_primary_positives() -> None:
    cohort = _cohort()
    result = ablation.run_ablation(cohort, bootstrap_replicates=20, nested_selection=False)
    coverage = result["target_coverage"]

    total = coverage["low_egfr_only"] + coverage["albuminuria_only"] + coverage["both"]
    assert total == coverage["primary_positives"] == int(cohort.frame["ckd_indicator"].sum())
    expected = (coverage["low_egfr_only"] + coverage["both"]) / coverage["primary_positives"]
    assert coverage["share_of_primary_positives_with_low_egfr"] == expected


def test_artifact_has_no_row_level_identifiers() -> None:
    result = ablation.run_ablation(_cohort(), bootstrap_replicates=20, nested_selection=False)
    payload = json.dumps(result, allow_nan=False).casefold()

    assert "seqn" not in payload
    assert "respondent_id" not in payload
    assert "out_of_fold" not in payload


def test_committed_ablation_artifact_matches_checksum_and_covers_four_sets() -> None:
    artifact_path = Path("data/processed/patient_finding_predictor_ablation.json")
    checksum_path = Path("data/processed/patient_finding_predictor_ablation.sha256")
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))

    digest, path = checksum_path.read_text(encoding="utf-8").split()
    assert sha256(artifact_path.read_bytes()).hexdigest() == digest
    assert path == artifact_path.as_posix()
    assert artifact["artifact_schema"] == "ckd_patient_finding_predictor_ablation_v1"
    assert set(artifact["feature_sets"]) == set(ablation.FEATURE_SETS)
    sizes = {entry["evaluated_n"] for entry in artifact["feature_sets"].values()}
    assert sizes == {artifact["evaluated_n"]}
    assert len(artifact["source_provenance"]["files"]) == 13
    assert artifact["feature_sets"]["current_pre_lab"]["selected_model"] in {
        "logistic_regression",
        "logistic_spline",
        "random_forest",
        "gradient_boosting",
    }
    payload = artifact_path.read_text(encoding="utf-8").casefold()
    assert "seqn" not in payload and "respondent_id" not in payload
