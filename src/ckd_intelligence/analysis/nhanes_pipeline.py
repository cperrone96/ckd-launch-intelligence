"""Build the two NHANES artifacts: the survey-weighted indicator estimate and the model.

Run ``python -m ckd_intelligence.analysis.nhanes_pipeline`` from the repository root.
With the verified NHANES snapshot under ``data/raw`` (see ``scripts/retrieve_surveys.py``)
the public-observed artifacts in ``data/processed`` and their manifests are rewritten.
Without it, a deterministic fixture run writes to ``data/processed/fixture`` only, so a
fixture can never overwrite official output.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import pandas as pd

from ckd_intelligence.analysis.artifacts import (
    PatientNeedEvidence,
    patient_finding_output_paths,
    patient_finding_source_provenance,
    patient_need_output_paths,
)
from ckd_intelligence.cohorts import nhanes_2017_2018 as nhanes
from ckd_intelligence.cohorts.definitions import CKDDefinition
from ckd_intelligence.modeling.patient_finding import (
    PRE_LAB_FEATURES,
    ModelComparison,
    train_patient_finding_models,
)
from ckd_intelligence.statistics.survey import weighted_prevalence

FIXTURE_PATH = Path("data/fixtures/nhanes_patient_need_representative.csv")
PRIMARY = CKDDefinition.primary().name
OFFICIAL_SCOPE = (
    "NHANES 2017-2018 MEC-exam-weighted U.S. civilian, "
    "noninstitutionalized adults excluding known pregnant participants"
)
FIXTURE_SCOPE = "Representative fixture only; not a population estimate"


@dataclass(frozen=True, slots=True)
class LoadedPeople:
    people: pd.DataFrame
    source_participant_count: int
    evidence_type: PatientNeedEvidence
    manifest: dict[str, Any]


def load_people(root: Path) -> LoadedPeople:
    """Load the verified NHANES snapshot, or the committed fixture when it is absent."""

    manifest = nhanes.load_manifest(root)
    if nhanes.snapshot_is_available(root, manifest):
        frame = nhanes.load_examined_participants(root)
        return LoadedPeople(
            people=nhanes.add_ckd_indicators(frame.people),
            source_participant_count=frame.source_participant_count,
            evidence_type="public_observed",
            manifest=manifest,
        )
    fixture = pd.read_csv(root / FIXTURE_PATH)
    return LoadedPeople(
        people=nhanes.add_ckd_indicators(fixture),
        source_participant_count=len(fixture),
        evidence_type="fixture_only",
        manifest=manifest,
    )


def _waterfall(loaded: LoadedPeople) -> list[dict[str, object]]:
    people = loaded.people
    adult = pd.to_numeric(people["age_years"], errors="coerce").ge(18)
    eligible = nhanes.eligible_domain(people)
    complete = eligible & people[PRIMARY].notna()
    stages = [
        ("NHANES 2017-2018 participants", loaded.source_participant_count),
        ("MEC examined with valid design and positive weight", len(people)),
        ("adults age 18+", int(adult.sum())),
        ("adults excluding known pregnancy", int(eligible.sum())),
        ("complete eGFR and UACR defining labs", int(complete.sum())),
        (
            "cross-sectional CKD indicator positive",
            int(people.loc[complete, PRIMARY].astype(bool).sum()),
        ),
    ]
    return [
        {"stage_order": order, "stage": stage, "people": int(count)}
        for order, (stage, count) in enumerate(stages, start=1)
    ]


def patient_need_artifact(root: Path, loaded: LoadedPeople) -> dict[str, Any]:
    """Survey-weighted prevalence of the primary and sensitivity indicators."""

    people = loaded.people
    eligible = nhanes.eligible_domain(people)
    complete = eligible & people[PRIMARY].notna()
    scope = OFFICIAL_SCOPE if loaded.evidence_type == "public_observed" else FIXTURE_SCOPE
    estimates: dict[str, dict[str, Any]] = {}
    for definition in nhanes.DEFINITIONS:
        estimate = weighted_prevalence(
            people[definition.name].tolist(),
            people["sample_weight"].tolist(),
            people["strata"].tolist(),
            people["psu"].tolist(),
            domain=eligible.tolist(),
            lonely_psu="error",
            source_population=scope,
        )
        record = asdict(estimate)
        record["unweighted_point"] = float(
            people.loc[complete, definition.name].astype(bool).mean()
        )
        estimates[definition.name] = record
    primary = estimates[PRIMARY]
    if loaded.evidence_type == "public_observed":
        input_provenance: list[dict[str, Any]] = list(loaded.manifest["files"])
    else:
        input_provenance = [
            {
                "name": FIXTURE_PATH.as_posix(),
                "sha256": sha256((root / FIXTURE_PATH).read_bytes()).hexdigest(),
            }
        ]
    return {
        "analysis_id": "nhanes-2017-2018-cross-sectional-ckd-patient-need",
        "evidence_type": loaded.evidence_type,
        "result_scope": scope,
        "source_release": "2017-2018",
        "source_manifest": nhanes.MANIFEST_PATH.as_posix(),
        "input_provenance": input_provenance,
        "definition": {
            "population": "Adults age 18+ excluding known pregnancy, with complete defining labs",
            "primary": (
                "Race-free CKD-EPI 2021 creatinine eGFR <60 mL/min/1.73 m2 OR UACR >=30 mg/g"
            ),
            "missing_labs": "Unknown and excluded; never false or zero",
            "interpretation": "Cross-sectional indicator, not confirmed chronic diagnosis",
            "pregnancy": "RIDEXPRG=1 excluded; codes 2/3 and missing/not-applicable retained",
            "uacr_source": "Official NHANES URDACT albumin creatinine ratio (mg/g)",
            "sensitivity": [
                "eGFR <60 only on common complete-case domain",
                "UACR >=30 mg/g only on common complete-case domain",
            ],
        },
        "survey_method": {
            "weight": "WTMEC2YR (2-year MEC exam weight)",
            "strata": "SDMVSTRA",
            "psu": "SDMVPSU",
            "variance": "Taylor linearization for a stratified PSU ratio",
            "confidence_interval": (
                "95% Student-t using PSU-minus-strata design degrees of freedom, bounded to [0,1]"
            ),
            "domain_handling": (
                "Full valid MEC-exam design retained; adult participants excluding "
                "known pregnancy form the domain; all definitions use the common "
                "complete-case subset"
            ),
            "lonely_psu": "error",
        },
        "waterfall": _waterfall(loaded),
        "estimates": estimates,
        "finding": (
            "Among complete cases, weighted cross-sectional CKD-indicator "
            f"prevalence was {primary['point']:.1%} "
            f"(95% CI {primary['ci_low']:.1%}–{primary['ci_high']:.1%}; "
            f"n={primary['denominator']:,}) in {scope}."
        ),
        "limitations": [
            "One cross-sectional survey cycle cannot confirm chronicity or support diagnosis.",
            (
                "A single serum creatinine and spot UACR are subject to biological "
                "and measurement variability."
            ),
            (
                "The complete-case estimate excludes eligible adults missing either "
                "defining laboratory measure and may differ if their prevalence differs."
            ),
            (
                "Estimates describe the documented survey population and should not "
                "be interpreted as individual risk."
            ),
        ],
    }


@dataclass(frozen=True, slots=True)
class ModelingCohort:
    frame: pd.DataFrame
    groups: pd.Series
    attrition: dict[str, object]


def modeling_cohort(loaded: LoadedPeople) -> ModelingCohort:
    """Complete-case cohort on the indicator domain and every available predictor."""

    people = loaded.people
    if loaded.evidence_type == "fixture_only":
        people = nhanes.add_ckd_indicators(_expanded_fixture(people))
    domain = nhanes.eligible_domain(people) & people[PRIMARY].notna()
    analytic = people.loc[domain].copy()
    features = [name for name in PRE_LAB_FEATURES if name in analytic.columns]
    complete = analytic.dropna(subset=features).copy()
    attrition: dict[str, object] = {
        "indicator_domain": len(analytic),
        "missing_by_predictor": {
            name: int(analytic[name].isna().sum())
            for name in features
            if analytic[name].isna().any()
        },
        "excluded_any_missing_predictor": len(analytic) - len(complete),
        "model_cohort": len(complete),
    }
    complete["ckd_indicator"] = complete[PRIMARY].astype(int)
    columns = [
        *features,
        "ckd_indicator",
        CKDDefinition.egfr_only().name,
        CKDDefinition.albuminuria_only().name,
    ]
    return ModelingCohort(
        frame=complete.loc[:, columns].reset_index(drop=True),
        groups=nhanes.survey_cluster_labels(complete).reset_index(drop=True),
        attrition=attrition,
    )


def _expanded_fixture(people: pd.DataFrame) -> pd.DataFrame:
    """Replicate the eight-row fixture into twelve pseudo-clusters for code-path tests."""

    races = ["Fixture Group A", "Fixture Group B", "Fixture Group C"]
    parts = []
    for replica in range(12):
        part = people.copy()
        part["age_years"] = (part["age_years"] + (replica % 5) - 2).clip(18, 85)
        part["race_ethnicity"] = [races[(i + replica) % 3] for i in range(len(part))]
        part["strata"] = replica + 1
        part["psu"] = 1
        parts.append(part)
    return pd.concat(parts, ignore_index=True)


def patient_finding_artifact(
    root: Path, loaded: LoadedPeople, cohort: ModelingCohort, comparison: ModelComparison
) -> dict[str, Any]:
    official = loaded.evidence_type == "public_observed"
    artifact = comparison.to_artifact()
    artifact.update(
        {
            "evidence_type": loaded.evidence_type,
            "source": (
                "Verified CDC/NCHS NHANES 2017-2018 public-use files"
                if official
                else "Deterministic expanded fixture; not a population finding"
            ),
            "analysis_population": (
                "NHANES 2017-2018 MEC-examined adults excluding known pregnancy with "
                "complete eGFR, UACR and pre-laboratory predictors"
                if official
                else "Deterministic fixture only"
            ),
            "cohort_attrition": cohort.attrition,
            "outcome": "Cross-sectional eGFR <60 or UACR >=30 mg/g indicator; not confirmed CKD",
            "performance_interpretation": (
                "Unweighted pooled out-of-fold metrics for the analytic cohort; "
                "not population estimates"
            ),
            "source_provenance": patient_finding_source_provenance(
                root / "data", loaded.evidence_type
            ),
        }
    )
    return artifact


def write_artifact(
    root: Path, artifact: dict[str, Any], paths: tuple[Path, Path], manifest_name: str | None
) -> str:
    """Write JSON, its SHA-256 sidecar and (for official output) the artifact manifest."""

    artifact_path, checksum_path = paths
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(artifact, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(
        "utf-8"
    )
    artifact_path.write_bytes(payload)
    digest = sha256(payload).hexdigest()
    relative = artifact_path.relative_to(root).as_posix()
    checksum_path.write_text(f"{digest}  {relative}\n", encoding="utf-8")
    if manifest_name is not None:
        manifest_path = root / "data/manifests" / manifest_name
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["artifact_sha256"] = digest
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return digest


def build(root: Path, *, bootstrap_replicates: int | None = None) -> dict[str, Any]:
    """Build both NHANES artifacts and return them with the fitted comparison."""

    loaded = load_people(root)
    official = loaded.evidence_type == "public_observed"
    need = patient_need_artifact(root, loaded)
    write_artifact(
        root,
        need,
        patient_need_output_paths(root / "data", loaded.evidence_type),
        "patient_need_summary.json" if official else None,
    )
    cohort = modeling_cohort(loaded)
    comparison = train_patient_finding_models(
        cohort.frame,
        cohort.groups,
        capacity=0.10,
        bootstrap_replicates=bootstrap_replicates or (1000 if official else 200),
        # The expanded fixture has too few clusters for an inner CV.
        nested_selection=official,
    )
    finding = patient_finding_artifact(root, loaded, cohort, comparison)
    write_artifact(
        root,
        finding,
        patient_finding_output_paths(root / "data", loaded.evidence_type),
        "patient_finding_model_comparison.json" if official else None,
    )
    return {
        "loaded": loaded,
        "patient_need": need,
        "cohort": cohort,
        "comparison": comparison,
        "patient_finding": finding,
    }


def main() -> None:
    result = build(Path.cwd())
    need = result["patient_need"]
    comparison: ModelComparison = result["comparison"]
    print(f"evidence_type: {need['evidence_type']}")
    print(need["finding"])
    for name, metrics in comparison.models.items():
        print(
            f"{name}: ROC-AUC {metrics.roc_auc:.3f} "
            f"({metrics.roc_auc_interval.low:.3f}-{metrics.roc_auc_interval.high:.3f}), "
            f"PR-AUC {metrics.pr_auc:.3f}, Brier {metrics.brier_score:.4f}"
        )


if __name__ == "__main__":
    main()
