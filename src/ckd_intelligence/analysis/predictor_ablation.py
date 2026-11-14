"""How far do honest additions move patient-finding discrimination?

Run ``python -m ckd_intelligence.analysis.predictor_ablation`` from the repository root
after ``scripts/retrieve_surveys.py``. Four feature sets go through the same nested
grouped cross-validation as the deployed model, on one shared complete-case cohort, and
each richer set is compared with the current pre-lab set by a paired cluster bootstrap.
The output is one aggregate artifact; the deployed scorer is not changed.
"""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ckd_intelligence.analysis.nhanes_pipeline import (
    LoadedPeople,
    ModelingCohort,
    load_people,
    modeling_cohort,
    write_artifact,
)
from ckd_intelligence.cohorts import nhanes_2017_2018 as nhanes
from ckd_intelligence.cohorts.definitions import CKDDefinition
from ckd_intelligence.cohorts.nhanes_2017_2018_ablation import (
    ABLATION_MANIFEST_PATH,
    load_ablation_predictors,
)
from ckd_intelligence.modeling.patient_finding import (
    ALLOWED_FEATURES,
    NESTED_SELECTION_MODEL,
    POINT_OF_CARE_LAB_FEATURES,
    PRE_LAB_FEATURES,
    QUESTIONNAIRE_ABLATION_FEATURES,
    _paired_metric_differences,
    train_patient_finding_models,
)

BASELINE = "current_pre_lab"
FEATURE_SETS: dict[str, tuple[str, ...]] = {
    BASELINE: PRE_LAB_FEATURES,
    "plus_questionnaire": PRE_LAB_FEATURES + QUESTIONNAIRE_ABLATION_FEATURES,
    "plus_point_of_care_labs": PRE_LAB_FEATURES + POINT_OF_CARE_LAB_FEATURES,
    "plus_labs_and_questionnaire": ALLOWED_FEATURES,
}
CAPACITY = 0.10
RANDOM_STATE = 20260910
OUTPUT_STEM = "patient_finding_predictor_ablation"


def ablation_cohort(loaded: LoadedPeople, extra: pd.DataFrame) -> ModelingCohort:
    """Join the ablation predictors, then keep people complete on every one of them."""

    people = loaded.people.merge(extra, on="respondent_id", how="left", validate="one_to_one")
    return modeling_cohort(replace(loaded, people=people), features=ALLOWED_FEATURES)


def _target_coverage(frame: pd.DataFrame) -> dict[str, float | int]:
    positive = frame["ckd_indicator"].astype(int).eq(1)
    low_egfr = frame[CKDDefinition.egfr_only().name].astype(int).eq(1)
    albuminuria = frame[CKDDefinition.albuminuria_only().name].astype(int).eq(1)
    counts = {
        "primary_positives": int(positive.sum()),
        "low_egfr_only": int((positive & low_egfr & ~albuminuria).sum()),
        "albuminuria_only": int((positive & albuminuria & ~low_egfr).sum()),
        "both": int((positive & low_egfr & albuminuria).sum()),
    }
    with_low_egfr = counts["low_egfr_only"] + counts["both"]
    return {
        **counts,
        "share_of_primary_positives_with_low_egfr": with_low_egfr / counts["primary_positives"],
    }


def run_ablation(
    cohort: ModelingCohort,
    *,
    bootstrap_replicates: int = 1000,
    nested_selection: bool = True,
) -> dict[str, Any]:
    """Score every feature set on the cohort and pair each richer set with the baseline."""

    y = cohort.frame["ckd_indicator"].astype(int).to_numpy()
    groups = cohort.groups.astype(str).to_numpy()
    results: dict[str, dict[str, Any]] = {}
    predictions: dict[str, np.ndarray] = {}
    for name, features in FEATURE_SETS.items():
        comparison = train_patient_finding_models(
            cohort.frame,
            cohort.groups,
            capacity=CAPACITY,
            random_state=RANDOM_STATE,
            bootstrap_replicates=bootstrap_replicates,
            nested_selection=nested_selection,
            features=list(features),
            export_scorer=False,
        )
        selected = comparison.models[comparison.selected_model]
        nested = comparison.models.get(NESTED_SELECTION_MODEL)
        results[name] = {
            "features": list(comparison.features),
            "evaluated_n": comparison.evaluated_n,
            "selected_model": comparison.selected_model,
            "roc_auc": selected.roc_auc,
            "roc_auc_interval": asdict(selected.roc_auc_interval),
            "pr_auc": selected.pr_auc,
            "pr_auc_interval": asdict(selected.pr_auc_interval),
            "precision_at_capacity": selected.precision,
            "precision_interval": asdict(selected.precision_interval),
            "recall_at_capacity": selected.recall,
            "recall_interval": asdict(selected.recall_interval),
            "nested_selection_roc_auc": nested.roc_auc if nested else None,
            "nested_selection_roc_auc_interval": (
                asdict(nested.roc_auc_interval) if nested else None
            ),
        }
        predictions[name] = np.asarray(comparison.out_of_fold_probabilities, dtype=float)

    paired: dict[str, dict[str, Any]] = {}
    for offset, name in enumerate(name for name in FEATURE_SETS if name != BASELINE):
        differences = _paired_metric_differences(
            y,
            predictions[name],
            predictions[BASELINE],
            groups,
            first_name=name,
            second_name=BASELINE,
            replicates=bootstrap_replicates,
            random_state=RANDOM_STATE + 100 + offset,
        )
        paired[name] = {metric: asdict(value) for metric, value in differences.items()}

    return {
        "artifact_schema": "ckd_patient_finding_predictor_ablation_v1",
        "evaluated_n": int(len(y)),
        "evaluated_prevalence": float(y.mean()),
        "capacity": CAPACITY,
        "cohort_attrition": cohort.attrition,
        "selection_policy": (
            "nested_grouped_cv_one_standard_error_rule"
            if nested_selection
            else "fixed_logistic_without_nested_selection"
        ),
        "feature_sets": results,
        "paired_vs_current": paired,
        "target_coverage": _target_coverage(cohort.frame),
        "intended_use": (
            "Exploratory measurement of how much extra predictors change discrimination; "
            "not a deployed model, a diagnosis or a clinical decision tool."
        ),
        "limitations": [
            "Every feature set is scored on the ablation cohort (complete on all predictors), "
            "so its current_pre_lab row can differ slightly from the published model.",
            "Medical-history and education questions are asked only of adults 20 and older, "
            "so the ablation cohort excludes 18- and 19-year-olds.",
            "Low hemoglobin is partly a consequence of CKD, not only a risk factor.",
            "Medication classes come from drug names; prescription reason codes are excluded.",
            "The ablation design was written after exploratory runs on the same data.",
            "No scorer is exported; a richer set may select a tree family.",
        ],
    }


def _provenance(root: Path) -> dict[str, Any]:
    paths = (nhanes.MANIFEST_PATH, ABLATION_MANIFEST_PATH)
    files = []
    for path in paths:
        manifest = json.loads((root / path).read_text(encoding="utf-8"))
        files += [{key: item[key] for key in ("name", "url", "sha256", "bytes")}
                  for item in manifest["files"]]  # fmt: skip
    return {"manifests": [path.as_posix() for path in paths], "files": files}


def main() -> int:
    root = Path.cwd()
    manifests = [nhanes.load_manifest(root)]
    manifests.append(json.loads((root / ABLATION_MANIFEST_PATH).read_text(encoding="utf-8")))
    if not all(nhanes.snapshot_is_available(root, manifest) for manifest in manifests):
        print("Raw NHANES files are missing. Run: python scripts/retrieve_surveys.py")
        return 1
    loaded = load_people(root)
    cohort = ablation_cohort(loaded, load_ablation_predictors(root))
    artifact = run_ablation(cohort)
    artifact["source_provenance"] = _provenance(root)
    processed = root / "data" / "processed"
    paths = (processed / f"{OUTPUT_STEM}.json", processed / f"{OUTPUT_STEM}.sha256")
    write_artifact(root, artifact, paths, None)
    for name, entry in artifact["feature_sets"].items():
        interval = entry["roc_auc_interval"]
        print(
            f"{name}: {entry['selected_model']} ROC-AUC {entry['roc_auc']:.3f} "
            f"({interval['low']:.3f}-{interval['high']:.3f}), PR-AUC {entry['pr_auc']:.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
