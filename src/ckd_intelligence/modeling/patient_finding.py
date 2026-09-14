"""Leakage-safe screening-opportunity model comparison.

This module supports an educational population-analytics demonstration. It does not
diagnose CKD, recommend care, or identify patients for clinical action.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, cast

import numpy as np
import pandas as pd
from sklearn.base import clone  # type: ignore[import-untyped]
from sklearn.compose import ColumnTransformer  # type: ignore[import-untyped]
from sklearn.ensemble import RandomForestClassifier  # type: ignore[import-untyped]
from sklearn.impute import SimpleImputer  # type: ignore[import-untyped]
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from sklearn.metrics import (  # type: ignore[import-untyped]
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import (  # type: ignore[import-untyped]
    StratifiedGroupKFold,
    cross_val_predict,
)
from sklearn.pipeline import Pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import OneHotEncoder, StandardScaler  # type: ignore[import-untyped]

PRE_LAB_FEATURES = (
    "age_years",
    "sex",
    "race_ethnicity",
    "body_mass_index",
    "systolic_blood_pressure",
    "diabetes_history",
    "hypertension_history",
    "smoking_status",
)
NUMERIC_FEATURES = frozenset(
    {"age_years", "body_mass_index", "systolic_blood_pressure"}
)
CATEGORICAL_FEATURES = frozenset(PRE_LAB_FEATURES) - NUMERIC_FEATURES
LEAKAGE_TOKENS = (
    "ckd",
    "egfr",
    "creatinine",
    "albumin",
    "uacr",
    "kidney_function",
    "renal_function",
    "cystatin",
    "blood_urea",
    "proteinuria",
    "dialysis",
)


class LeakageError(ValueError):
    """Raised when a requested feature could reveal the laboratory-defined outcome."""


class FeatureValidationError(ValueError):
    """Raised when model features or scoring input violate the documented contract."""


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    mean_probability: float
    observed_rate: float
    n: int


@dataclass(frozen=True, slots=True)
class ModelMetrics:
    roc_auc: float
    pr_auc: float
    brier_score: float
    precision: float
    recall: float
    threshold: float
    confusion_matrix: dict[str, int]
    calibration_bins: tuple[CalibrationBin, ...]
    mean_probability: float
    n: int
    positives: int


@dataclass(frozen=True, slots=True)
class SubgroupMetrics:
    group: str
    value: str
    n: int
    positives: int
    prevalence: float
    precision: float | None
    recall: float | None
    brier_score: float
    caveat: str | None


@dataclass(frozen=True, slots=True)
class SplitSummary:
    strategy: str
    development_n: int
    holdout_n: int
    development_groups: frozenset[str]
    holdout_groups: frozenset[str]
    threshold_source: str
    random_state: int


@dataclass(frozen=True, slots=True)
class LogisticScorer:
    """Portable, JSON-safe logistic scorer; no pickle or executable artifact."""

    feature_order: tuple[str, ...]
    numeric_medians: Mapping[str, float]
    numeric_means: Mapping[str, float]
    numeric_scales: Mapping[str, float]
    categorical_modes: Mapping[str, str]
    categorical_levels: Mapping[str, tuple[str, ...]]
    coefficients: tuple[float, ...]
    intercept: float

    def _validated(self, record: Mapping[str, object]) -> dict[str, object]:
        leaked = sorted(name for name in record if _looks_like_leakage(name))
        if leaked:
            raise LeakageError(
                f"scoring input contains outcome-derived fields: {', '.join(leaked)}"
            )
        extras = sorted(set(record) - set(self.feature_order))
        if extras:
            raise FeatureValidationError(f"unexpected scoring fields: {', '.join(extras)}")
        missing = sorted(set(self.feature_order) - set(record))
        if missing:
            raise FeatureValidationError(f"missing required scoring fields: {', '.join(missing)}")
        validated: dict[str, object] = {}
        for name in self.feature_order:
            value = record[name]
            if value is None or (isinstance(value, float) and math.isnan(value)):
                raise FeatureValidationError(f"{name} must be present for scoring")
            if name in NUMERIC_FEATURES:
                try:
                    number = float(value)  # type: ignore[arg-type]
                except (TypeError, ValueError) as exc:
                    raise FeatureValidationError(f"{name} must be numeric") from exc
                if not math.isfinite(number):
                    raise FeatureValidationError(f"{name} must be finite")
                lower, upper = _numeric_range(name)
                if not lower <= number <= upper:
                    raise FeatureValidationError(
                        f"{name} must be between {lower:g} and {upper:g}"
                    )
                validated[name] = number
            else:
                text = str(value).strip()
                if not text or text not in self.categorical_levels[name]:
                    allowed = ", ".join(self.categorical_levels[name])
                    raise FeatureValidationError(f"{name} must be one of: {allowed}")
                validated[name] = text
        return validated

    def score_one(self, record: Mapping[str, object]) -> float:
        """Score one complete, range-checked record as an educational probability."""

        values = self._validated(record)
        vector: list[float] = []
        for name in self.feature_order:
            if name in NUMERIC_FEATURES:
                number = float(cast(float | int | str, values[name]))
                scale = self.numeric_scales[name]
                vector.append((number - self.numeric_means[name]) / scale)
        for name in self.feature_order:
            if name in CATEGORICAL_FEATURES:
                vector.extend(
                    float(values[name] == level) for level in self.categorical_levels[name]
                )
        linear = self.intercept + float(np.dot(np.asarray(vector), np.asarray(self.coefficients)))
        return float(1.0 / (1.0 + math.exp(-max(-709.0, min(709.0, linear)))))

    def as_dict(self) -> dict[str, object]:
        return {
            "format": "portable_logistic_json_v1",
            "feature_order": list(self.feature_order),
            "numeric_medians": dict(self.numeric_medians),
            "numeric_means": dict(self.numeric_means),
            "numeric_scales": dict(self.numeric_scales),
            "categorical_modes": dict(self.categorical_modes),
            "categorical_levels": {
                name: list(levels) for name, levels in self.categorical_levels.items()
            },
            "coefficients": list(self.coefficients),
            "intercept": self.intercept,
        }


@dataclass(frozen=True, slots=True)
class ModelComparison:
    models: Mapping[str, ModelMetrics]
    selected_model: str
    selection_probabilities: tuple[float, ...]
    selected_threshold: float
    threshold_capacity: float | int
    holdout_prevalence: float
    holdout_n: int
    split: SplitSummary
    subgroups: Mapping[str, tuple[SubgroupMetrics, ...]]
    cohort_sensitivity: Mapping[str, Mapping[str, float | int | str]]
    scorer: LogisticScorer
    features: tuple[str, ...]
    intended_use: str
    limitations: tuple[str, ...]

    @property
    def brier_score(self) -> float:
        return self.models[self.selected_model].brier_score

    @property
    def pr_auc(self) -> float:
        return self.models[self.selected_model].pr_auc

    def to_artifact(self) -> dict[str, object]:
        """Return aggregate, deterministic JSON content without row-level predictions."""

        return {
            "artifact_schema": "ckd_patient_finding_model_comparison_v1",
            "selected_model": self.selected_model,
            "selected_threshold": self.selected_threshold,
            "threshold_capacity": self.threshold_capacity,
            "holdout_prevalence": self.holdout_prevalence,
            "holdout_n": self.holdout_n,
            "features": list(self.features),
            "split": {
                "strategy": self.split.strategy,
                "development_n": self.split.development_n,
                "holdout_n": self.split.holdout_n,
                "development_group_count": len(self.split.development_groups),
                "holdout_group_count": len(self.split.holdout_groups),
                "threshold_source": self.split.threshold_source,
                "random_state": self.split.random_state,
            },
            "models": {name: asdict(metrics) for name, metrics in self.models.items()},
            "subgroups": {
                dimension: [asdict(metric) for metric in metrics]
                for dimension, metrics in self.subgroups.items()
            },
            "cohort_sensitivity": self.cohort_sensitivity,
            "scorer": self.scorer.as_dict(),
            "intended_use": self.intended_use,
            "limitations": list(self.limitations),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_artifact(), sort_keys=True, indent=2) + "\n"


def _looks_like_leakage(column: str) -> bool:
    normalized = column.strip().casefold().replace("-", "_").replace(" ", "_")
    return any(token in normalized for token in LEAKAGE_TOKENS)


def _numeric_range(name: str) -> tuple[float, float]:
    ranges = {
        "age_years": (18.0, 120.0),
        "body_mass_index": (10.0, 80.0),
        "systolic_blood_pressure": (60.0, 260.0),
    }
    return ranges[name]


def build_pre_lab_features(
    frame: pd.DataFrame, requested: Sequence[str] | None = None
) -> pd.DataFrame:
    """Return only explicitly allowed variables plausibly available before kidney labs."""

    chosen = list(requested) if requested is not None else [
        name for name in PRE_LAB_FEATURES if name in frame.columns
    ]
    leaked = sorted(name for name in chosen if _looks_like_leakage(name))
    if leaked:
        raise LeakageError(f"outcome-defining or derived fields requested: {', '.join(leaked)}")
    unsupported = sorted(set(chosen) - set(PRE_LAB_FEATURES))
    if unsupported:
        raise FeatureValidationError(
            f"fields not in the pre-laboratory allowlist: {', '.join(unsupported)}"
        )
    missing = sorted(set(chosen) - set(frame.columns))
    if missing:
        raise FeatureValidationError(f"requested fields are absent: {', '.join(missing)}")
    if "age_years" not in chosen:
        raise FeatureValidationError("age_years is required for this adult cohort model")
    return frame.loc[:, chosen].copy()


def _pipeline(kind: str, features: Sequence[str], random_state: int) -> Pipeline:
    numeric = [name for name in features if name in NUMERIC_FEATURES]
    categorical = [name for name in features if name in CATEGORICAL_FEATURES]
    transformer = ColumnTransformer(
        [
            (
                "numeric",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="median")),
                        ("scaler", StandardScaler()),
                    ]
                ),
                numeric,
            ),
            (
                "categorical",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        ("one_hot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
                    ]
                ),
                categorical,
            ),
        ],
        remainder="drop",
    )
    if kind == "logistic_regression":
        estimator: Any = LogisticRegression(max_iter=2000, random_state=random_state)
    elif kind == "random_forest":
        estimator = RandomForestClassifier(
            n_estimators=200,
            max_depth=6,
            min_samples_leaf=10,
            random_state=random_state,
            n_jobs=1,
        )
    else:
        raise ValueError(f"unsupported model kind: {kind}")
    return Pipeline([("preprocess", transformer), ("model", estimator)])


def _calibration_bins(y: np.ndarray, probabilities: np.ndarray) -> tuple[CalibrationBin, ...]:
    frame = pd.DataFrame({"y": y, "probability": probabilities})
    unique_probabilities = int(frame["probability"].nunique())
    if unique_probabilities == 1:
        return (
            CalibrationBin(
                mean_probability=float(frame["probability"].iloc[0]),
                observed_rate=float(frame["y"].mean()),
                n=int(len(frame)),
            ),
        )
    bins = pd.qcut(
        frame["probability"],
        q=min(5, unique_probabilities),
        labels=False,
        duplicates="drop",
    )
    output: list[CalibrationBin] = []
    for _, group in frame.groupby(bins, observed=True):
        output.append(
            CalibrationBin(
                mean_probability=float(group["probability"].mean()),
                observed_rate=float(group["y"].mean()),
                n=int(len(group)),
            )
        )
    return tuple(output)


def _metrics(y: np.ndarray, probabilities: np.ndarray, threshold: float) -> ModelMetrics:
    predicted = probabilities >= threshold
    matrix = confusion_matrix(y, predicted, labels=[0, 1])
    tn, fp, fn, tp = (int(value) for value in matrix.ravel())
    roc = float(roc_auc_score(y, probabilities)) if len(np.unique(y)) == 2 else float("nan")
    pr = (
        float(average_precision_score(y, probabilities))
        if int(y.sum()) > 0
        else float("nan")
    )
    return ModelMetrics(
        roc_auc=roc,
        pr_auc=pr,
        brier_score=float(brier_score_loss(y, probabilities)),
        precision=float(precision_score(y, predicted, zero_division=0)),
        recall=float(recall_score(y, predicted, zero_division=0)),
        threshold=float(threshold),
        confusion_matrix={
            "true_negative": tn,
            "false_positive": fp,
            "false_negative": fn,
            "true_positive": tp,
        },
        calibration_bins=_calibration_bins(y, probabilities),
        mean_probability=float(probabilities.mean()),
        n=int(len(y)),
        positives=int(y.sum()),
    )


def _capacity_count(total: int, capacity: float | int) -> int:
    if isinstance(capacity, bool):
        raise ValueError("capacity must be a positive count or a fraction in (0, 1]")
    if isinstance(capacity, int):
        if not 1 <= capacity <= total:
            raise ValueError("integer capacity must be between 1 and the available observations")
        return capacity
    if not math.isfinite(capacity) or not 0 < capacity <= 1:
        raise ValueError("fractional capacity must be in (0, 1]")
    return max(1, min(total, int(round(total * capacity))))


def select_operating_threshold(report: ModelComparison, capacity: float | int) -> float:
    """Choose a capacity threshold only from out-of-fold development predictions."""

    probabilities = np.asarray(report.selection_probabilities, dtype=float)
    count = _capacity_count(len(probabilities), capacity)
    descending = np.sort(probabilities)[::-1]
    return float(descending[count - 1])


def _subgroups(
    holdout: pd.DataFrame,
    y: np.ndarray,
    probabilities: np.ndarray,
    threshold: float,
) -> dict[str, tuple[SubgroupMetrics, ...]]:
    age = pd.to_numeric(holdout["age_years"], errors="coerce")
    dimensions: dict[str, pd.Series] = {
        "age_band": pd.cut(
            age,
            bins=[17, 39, 59, 120],
            labels=["18-39", "40-59", "60+"],
            include_lowest=True,
        ).astype("string"),
        "sex": holdout["sex"].astype("string"),
    }
    output: dict[str, tuple[SubgroupMetrics, ...]] = {}
    for dimension, values in dimensions.items():
        records: list[SubgroupMetrics] = []
        for value in sorted(values.dropna().unique()):
            mask = values.eq(value).fillna(False).to_numpy(dtype=bool)
            group_y = y[mask]
            group_p = probabilities[mask]
            positives = int(group_y.sum())
            caveat = None
            if len(group_y) < 30 or positives < 5 or len(group_y) - positives < 5:
                caveat = (
                    "Small subgroup/event count; metrics are descriptive and potentially unstable."
                )
            predicted = group_p >= threshold
            if int(predicted.sum()) == 0:
                no_flags = (
                    "No records were flagged at the selected threshold; precision is undefined."
                )
                caveat = f"{caveat} {no_flags}" if caveat else no_flags
            records.append(
                SubgroupMetrics(
                    group=dimension,
                    value=str(value),
                    n=int(len(group_y)),
                    positives=positives,
                    prevalence=float(group_y.mean()),
                    precision=(
                        float(precision_score(group_y, predicted, zero_division=0))
                        if int(predicted.sum()) > 0
                        else None
                    ),
                    recall=(
                        float(recall_score(group_y, predicted, zero_division=0))
                        if positives > 0
                        else None
                    ),
                    brier_score=float(brier_score_loss(group_y, group_p)),
                    caveat=caveat,
                )
            )
        output[dimension] = tuple(records)
    return output


def _portable_scorer(pipeline: Pipeline, features: Sequence[str]) -> LogisticScorer:
    preprocess: ColumnTransformer = pipeline.named_steps["preprocess"]
    model: LogisticRegression = pipeline.named_steps["model"]
    numeric = [name for name in features if name in NUMERIC_FEATURES]
    categorical = [name for name in features if name in CATEGORICAL_FEATURES]
    numeric_pipeline: Pipeline = preprocess.named_transformers_["numeric"]
    imputer: SimpleImputer = numeric_pipeline.named_steps["imputer"]
    scaler: StandardScaler = numeric_pipeline.named_steps["scaler"]
    categorical_pipeline: Pipeline = preprocess.named_transformers_["categorical"]
    categorical_imputer: SimpleImputer = categorical_pipeline.named_steps["imputer"]
    encoder: OneHotEncoder = categorical_pipeline.named_steps["one_hot"]
    return LogisticScorer(
        feature_order=tuple(features),
        numeric_medians={
            name: float(value)
            for name, value in zip(numeric, imputer.statistics_, strict=True)
        },
        numeric_means={
            name: float(value) for name, value in zip(numeric, scaler.mean_, strict=True)
        },
        numeric_scales={
            name: float(value) for name, value in zip(numeric, scaler.scale_, strict=True)
        },
        categorical_modes={
            name: str(value)
            for name, value in zip(categorical, categorical_imputer.statistics_, strict=True)
        },
        categorical_levels={
            name: tuple(str(value) for value in levels)
            for name, levels in zip(categorical, encoder.categories_, strict=True)
        },
        coefficients=tuple(float(value) for value in model.coef_[0]),
        intercept=float(model.intercept_[0]),
    )


def train_patient_finding_models(
    train: pd.DataFrame,
    groups: Sequence[object] | pd.Series,
    *,
    capacity: float | int = 0.10,
    random_state: int = 20260910,
    target_column: str = "ckd_indicator",
) -> ModelComparison:
    """Compare no-skill, logistic, and tree models with a group-isolated holdout."""

    if target_column not in train:
        raise FeatureValidationError(f"missing target column: {target_column}")
    if len(train) != len(groups):
        raise FeatureValidationError("groups must have one value per training row")
    y_series = pd.to_numeric(train[target_column], errors="coerce")
    if y_series.isna().any() or not set(y_series.unique()).issubset({0, 1}):
        raise FeatureValidationError("target must be complete and binary")
    if y_series.nunique() < 2:
        raise FeatureValidationError("target must contain both outcome classes")
    group_series = pd.Series(groups, index=train.index, dtype="string")
    if group_series.isna().any() or group_series.nunique() < 10:
        raise FeatureValidationError("at least ten complete groups are required")

    features = build_pre_lab_features(train)
    if not {"age_years", "sex", "race_ethnicity"}.issubset(features.columns):
        raise FeatureValidationError("age_years, sex, and race_ethnicity are required")
    y = y_series.astype(int).to_numpy()
    split_cv = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=random_state)
    development_index, holdout_index = next(split_cv.split(features, y, group_series))
    development = features.iloc[development_index].reset_index(drop=True)
    holdout = features.iloc[holdout_index].reset_index(drop=True)
    y_development = y[development_index]
    y_holdout = y[holdout_index]
    development_groups = group_series.iloc[development_index].reset_index(drop=True)

    oof_cv = StratifiedGroupKFold(n_splits=4, shuffle=True, random_state=random_state + 1)
    models: dict[str, Pipeline] = {
        name: _pipeline(name, list(features.columns), random_state)
        for name in ("logistic_regression", "random_forest")
    }
    oof: dict[str, np.ndarray] = {}
    fitted: dict[str, Pipeline] = {}
    for name, pipeline in models.items():
        oof[name] = cross_val_predict(
            clone(pipeline),
            development,
            y_development,
            groups=development_groups,
            cv=oof_cv,
            method="predict_proba",
            n_jobs=1,
        )[:, 1]
        fitted[name] = clone(pipeline).fit(development, y_development)

    temporary = ModelComparison(
        models={},
        selected_model="logistic_regression",
        selection_probabilities=tuple(float(value) for value in oof["logistic_regression"]),
        selected_threshold=0.5,
        threshold_capacity=capacity,
        holdout_prevalence=float(y_holdout.mean()),
        holdout_n=int(len(y_holdout)),
        split=SplitSummary(
            strategy="stratified grouped 5-fold partition; one fold untouched as holdout",
            development_n=int(len(development_index)),
            holdout_n=int(len(holdout_index)),
            development_groups=frozenset(development_groups.astype(str)),
            holdout_groups=frozenset(group_series.iloc[holdout_index].astype(str)),
            threshold_source="out_of_fold_development_predictions",
            random_state=random_state,
        ),
        subgroups={},
        cohort_sensitivity={},
        scorer=_portable_scorer(fitted["logistic_regression"], list(features.columns)),
        features=tuple(features.columns),
        intended_use=(
            "Educational comparison of population-level screening opportunity; "
            "not a diagnosis or clinical decision tool."
        ),
        limitations=(),
    )
    threshold = select_operating_threshold(temporary, capacity)
    holdout_probabilities = {
        name: pipeline.predict_proba(holdout)[:, 1] for name, pipeline in fitted.items()
    }
    prevalence = float(y_development.mean())
    no_skill_probabilities = np.full(len(y_holdout), prevalence, dtype=float)
    metrics: dict[str, ModelMetrics] = {
        "prevalence_no_skill": _metrics(y_holdout, no_skill_probabilities, threshold),
        "logistic_regression": _metrics(
            y_holdout, holdout_probabilities["logistic_regression"], threshold
        ),
        "random_forest": _metrics(y_holdout, holdout_probabilities["random_forest"], threshold),
    }

    sensitivity: dict[str, Mapping[str, float | int | str]] = {
        "primary_definition": {
            "target": target_column,
            "holdout_n": int(len(y_holdout)),
            "holdout_prevalence": float(y_holdout.mean()),
        }
    }
    for alternative in ("sensitivity_egfr_only", "sensitivity_albuminuria_only"):
        if alternative in train:
            values = pd.to_numeric(train.iloc[holdout_index][alternative], errors="coerce")
            valid = values.notna().to_numpy()
            alternative_y = values.loc[values.notna()].astype(int).to_numpy()
            alternative_p = holdout_probabilities["logistic_regression"][valid]
            if len(alternative_y) and len(np.unique(alternative_y)) == 2:
                sensitivity[alternative] = {
                    "holdout_n": int(len(alternative_y)),
                    "holdout_prevalence": float(alternative_y.mean()),
                    "roc_auc": float(roc_auc_score(alternative_y, alternative_p)),
                    "pr_auc": float(average_precision_score(alternative_y, alternative_p)),
                }

    return ModelComparison(
        models=metrics,
        selected_model="logistic_regression",
        selection_probabilities=temporary.selection_probabilities,
        selected_threshold=threshold,
        threshold_capacity=capacity,
        holdout_prevalence=float(y_holdout.mean()),
        holdout_n=int(len(y_holdout)),
        split=temporary.split,
        subgroups=_subgroups(
            holdout,
            y_holdout,
            holdout_probabilities["logistic_regression"],
            threshold,
        ),
        cohort_sensitivity=sensitivity,
        scorer=temporary.scorer,
        features=tuple(features.columns),
        intended_use=temporary.intended_use,
        limitations=(
            "Cross-sectional NHANES laboratory indicators cannot confirm chronic disease.",
            "Performance metrics are unweighted and describe this held-out analytic sample, "
            "not U.S. population performance.",
            "Demographics-only predictors omit clinical context and must not be used for "
            "care decisions.",
            "Subgroup metrics are descriptive; small event counts can be unstable.",
        ),
    )
