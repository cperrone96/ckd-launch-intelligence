"""Leakage-controlled risk model for a laboratory-defined CKD indicator.

Predictors are restricted to an allowlist of variables that are available before
kidney laboratory testing (demographics, body measures, blood pressure, diabetes and
hypertension history, smoking). Performance is estimated with survey-cluster-grouped
cross-validation, and the selected logistic model is exported as a portable JSON
scorer. The model ranks population-level screening opportunity; it does not
diagnose CKD.
"""

from __future__ import annotations

import json
import math
import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, cast

import numpy as np
import pandas as pd
from scipy.interpolate import BSpline
from sklearn.compose import ColumnTransformer  # type: ignore[import-untyped]
from sklearn.ensemble import (  # type: ignore[import-untyped]
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.exceptions import ConvergenceWarning  # type: ignore[import-untyped]
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
    GridSearchCV,
    StratifiedGroupKFold,
)
from sklearn.pipeline import Pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import (  # type: ignore[import-untyped]
    OneHotEncoder,
    SplineTransformer,
    StandardScaler,
)

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
DEMOGRAPHIC_FEATURES = ("age_years", "sex", "race_ethnicity")
DEMOGRAPHICS_MODEL = "logistic_demographics_only"
# Candidate model families, simplest first. Each is tuned by grid search on an inner
# grouped CV (log loss) nested inside every outer fit set.
MODEL_FAMILIES = ("logistic_regression", "logistic_spline", "random_forest", "gradient_boosting")
SCORER_FAMILIES = frozenset({"logistic_regression", "logistic_spline"})
TUNING_GRIDS: dict[str, dict[str, list[Any]]] = {
    "logistic_regression": {"model__C": [0.001, 0.01, 0.1, 1.0, 10.0, 100.0]},
    "logistic_spline": {"model__C": [0.01, 0.1, 1.0, 10.0, 100.0, 1000.0]},
    "random_forest": {
        "model__min_samples_leaf": [1, 2, 5, 10, 20, 40],
        "model__max_depth": [4, 6, 10, None],
    },
    "gradient_boosting": {
        "model__learning_rate": [0.01, 0.03, 0.1],
        "model__max_leaf_nodes": [2, 3, 4, 8, 16],
    },
}
# Used only when nested selection is switched off (fixture runs and fast unit tests).
DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    "logistic_regression": {"model__C": 1.0},
    "logistic_spline": {"model__C": 1.0},
    "random_forest": {"model__min_samples_leaf": 10, "model__max_depth": 6},
    "gradient_boosting": {"model__learning_rate": 0.1, "model__max_leaf_nodes": 4},
}
INNER_SPLITS = 5
NESTED_SELECTION_MODEL = "nested_selection"
SELECTION_RULE = (
    "Declared before the nested run: in each fit set every family is tuned by inner "
    f"grouped {INNER_SPLITS}-fold CV on log loss, and the simplest family (order: "
    + ", ".join(MODEL_FAMILIES)
    + ") whose mean inner log loss is within one standard error of the best family's "
    "is selected. The outer folds only measure the result."
)
LOGISTIC_MAX_ITER = 5000
NUMERIC_FEATURES = frozenset({"age_years", "body_mass_index", "systolic_blood_pressure"})
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


class CapacityBoundaryError(ValueError):
    """Raised when a scalar threshold cannot represent an exact tied capacity."""


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    mean_probability: float
    observed_rate: float
    n: int


@dataclass(frozen=True, slots=True)
class UncertaintyInterval:
    low: float
    high: float
    method: str
    requested_replicates: int
    valid_replicates: int
    cluster_count: int
    caveat: str | None


@dataclass(frozen=True, slots=True)
class CapacityDecision:
    selected: tuple[bool, ...]
    threshold: float
    requested_count: int
    selected_count: int
    selected_share: float
    tie_policy: str


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
    requested_count: int
    selected_count: int
    selected_share: float
    tie_policy: str
    roc_auc_interval: UncertaintyInterval
    pr_auc_interval: UncertaintyInterval
    brier_interval: UncertaintyInterval
    precision_interval: UncertaintyInterval
    recall_interval: UncertaintyInterval


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
    precision_interval: UncertaintyInterval | None
    recall_interval: UncertaintyInterval | None
    brier_interval: UncertaintyInterval | None
    caveat: str | None
    roc_auc: float | None = None
    mean_probability: float | None = None
    flagged_share: float | None = None


@dataclass(frozen=True, slots=True)
class PairedDifference:
    metric: str
    comparison: str
    estimate: float
    interval: UncertaintyInterval
    interpretation: str


@dataclass(frozen=True, slots=True)
class CrossValidationSummary:
    strategy: str
    folds: int
    evaluated_n: int
    group_count: int
    scoring_fold_sizes: tuple[int, ...]
    scoring_fold_group_counts: tuple[int, ...]
    threshold_source: str
    random_state: int


@dataclass(frozen=True, slots=True)
class LogisticScorer:
    """Portable, JSON-safe logistic scorer; no pickle or executable artifact."""

    feature_order: tuple[str, ...]
    numeric_means: Mapping[str, float]
    numeric_scales: Mapping[str, float]
    categorical_levels: Mapping[str, tuple[str, ...]]
    coefficients: tuple[float, ...]
    intercept: float
    artifact_version: str = "1.0.0"
    missing_value_policy: str = "reject"
    unknown_category_policy: str = "reject"
    coefficient_precision: str = "float64"
    numeric_encoding: str = "standardize"
    spline_knots: Mapping[str, tuple[float, ...]] = field(default_factory=dict)
    spline_degree: int = 3

    def _numeric_terms(self, name: str, number: float) -> list[float]:
        if self.numeric_encoding == "standardize":
            return [(number - self.numeric_means[name]) / self.numeric_scales[name]]
        # Cubic B-spline basis with constant extrapolation, matching
        # sklearn.preprocessing.SplineTransformer(extrapolation="constant").
        knots = np.asarray(self.spline_knots[name], dtype=float)
        degree = self.spline_degree
        clamped = min(max(number, float(knots[degree])), float(knots[-degree - 1]))
        basis = BSpline.design_matrix(np.asarray([clamped]), knots, degree).toarray()[0]
        return [float(value) for value in basis]

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
                if not _is_json_number(value):
                    raise FeatureValidationError(f"{name} must be a JSON number")
                number = float(cast(float | int, value))
                if not math.isfinite(number):
                    raise FeatureValidationError(f"{name} must be finite")
                lower, upper = _numeric_range(name)
                if not lower <= number <= upper:
                    raise FeatureValidationError(f"{name} must be between {lower:g} and {upper:g}")
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
                vector.extend(
                    self._numeric_terms(name, float(cast(float | int | str, values[name])))
                )
        for name in self.feature_order:
            if name in CATEGORICAL_FEATURES:
                vector.extend(
                    float(values[name] == level) for level in self.categorical_levels[name]
                )
        linear = self.intercept + float(np.dot(np.asarray(vector), np.asarray(self.coefficients)))
        if linear >= 0:
            return float(1.0 / (1.0 + math.exp(-linear)))
        exponential = math.exp(linear)
        return float(exponential / (1.0 + exponential))

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "format": "portable_logistic_json_v1",
            "artifact_version": self.artifact_version,
            "missing_value_policy": self.missing_value_policy,
            "unknown_category_policy": self.unknown_category_policy,
            "coefficient_precision": self.coefficient_precision,
            "feature_order": list(self.feature_order),
            "numeric_means": dict(self.numeric_means),
            "numeric_scales": dict(self.numeric_scales),
            "categorical_levels": {
                name: list(levels) for name, levels in self.categorical_levels.items()
            },
            "required_fields": [
                (
                    {
                        "name": name,
                        "type": "number",
                        "minimum": _numeric_range(name)[0],
                        "maximum": _numeric_range(name)[1],
                    }
                    if name in NUMERIC_FEATURES
                    else {
                        "name": name,
                        "type": "string",
                        "allowed_values": list(self.categorical_levels[name]),
                    }
                )
                for name in self.feature_order
            ],
            "coefficients": list(self.coefficients),
            "intercept": self.intercept,
        }
        if self.numeric_encoding != "standardize":
            payload["numeric_encoding"] = self.numeric_encoding
            payload["spline_knots"] = {
                name: list(knots) for name, knots in self.spline_knots.items()
            }
            payload["spline_degree"] = self.spline_degree
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> LogisticScorer:
        """Load and validate the versioned portable scorer contract."""

        required = {
            "format",
            "artifact_version",
            "missing_value_policy",
            "unknown_category_policy",
            "coefficient_precision",
            "feature_order",
            "numeric_means",
            "numeric_scales",
            "categorical_levels",
            "required_fields",
            "coefficients",
            "intercept",
        }
        missing = sorted(required - set(payload))
        if missing:
            raise FeatureValidationError(f"scorer artifact missing fields: {', '.join(missing)}")
        numeric_encoding = payload.get("numeric_encoding", "standardize")
        if numeric_encoding not in ("standardize", "cubic_bspline"):
            raise FeatureValidationError("unsupported numeric encoding")
        if (
            payload["format"] != "portable_logistic_json_v1"
            or payload["artifact_version"] != "1.0.0"
        ):
            raise FeatureValidationError("unsupported scorer artifact format or version")
        if payload["missing_value_policy"] != "reject":
            raise FeatureValidationError("unsupported missing-value policy")
        if payload["unknown_category_policy"] != "reject":
            raise FeatureValidationError("unsupported unknown-category policy")
        if payload["coefficient_precision"] != "float64":
            raise FeatureValidationError("unsupported coefficient precision")
        try:
            feature_order = tuple(
                str(value) for value in cast(list[object], payload["feature_order"])
            )
            numeric_means = {
                str(name): float(cast(float | int | str, value))
                for name, value in cast(dict[object, object], payload["numeric_means"]).items()
            }
            numeric_scales = {
                str(name): float(cast(float | int | str, value))
                for name, value in cast(dict[object, object], payload["numeric_scales"]).items()
            }
            categorical_levels = {
                str(name): tuple(str(level) for level in cast(list[object], values))
                for name, values in cast(
                    dict[object, object], payload["categorical_levels"]
                ).items()
            }
            coefficients = tuple(
                float(cast(float | int | str, value))
                for value in cast(list[object], payload["coefficients"])
            )
            intercept = float(cast(float | int | str, payload["intercept"]))
            spline_knots = {
                str(name): tuple(
                    float(cast(float | int | str, knot)) for knot in cast(list[object], knots)
                )
                for name, knots in cast(
                    dict[object, object], payload.get("spline_knots", {})
                ).items()
            }
            spline_degree = int(cast(int, payload.get("spline_degree", 3)))
        except (TypeError, ValueError) as exc:
            raise FeatureValidationError("scorer artifact contains invalid field types") from exc
        raw_numeric_values: list[object] = [
            *cast(dict[object, object], payload["numeric_means"]).values(),
            *cast(dict[object, object], payload["numeric_scales"]).values(),
            *cast(list[object], payload["coefficients"]),
            payload["intercept"],
        ]
        if any(not _is_json_number(value) for value in raw_numeric_values):
            raise FeatureValidationError("scorer numeric fields must be JSON numbers")
        if not feature_order or len(set(feature_order)) != len(feature_order):
            raise FeatureValidationError("feature_order must contain unique fields")
        if set(feature_order) - set(PRE_LAB_FEATURES):
            raise FeatureValidationError("scorer artifact contains unsupported features")
        expected_numeric = {name for name in feature_order if name in NUMERIC_FEATURES}
        if set(numeric_means) != expected_numeric or set(numeric_scales) != expected_numeric:
            raise FeatureValidationError(
                "scorer numeric preprocessing fields do not match feature_order"
            )
        expected_categorical = {name for name in feature_order if name in CATEGORICAL_FEATURES}
        if set(categorical_levels) != expected_categorical or any(
            not levels or len(set(levels)) != len(levels) for levels in categorical_levels.values()
        ):
            raise FeatureValidationError("scorer categorical levels do not match feature_order")
        if numeric_encoding == "cubic_bspline":
            if set(spline_knots) != expected_numeric or spline_degree != 3:
                raise FeatureValidationError("spline knots do not match feature_order")
            if any(
                len(knots) < 2 * spline_degree + 2
                or any(b < a for a, b in zip(knots, knots[1:], strict=False))
                or not all(math.isfinite(knot) for knot in knots)
                for knots in spline_knots.values()
            ):
                raise FeatureValidationError("spline knots must be finite and nondecreasing")
            terms_per_numeric = {
                name: len(knots) - spline_degree - 1 for name, knots in spline_knots.items()
            }
        else:
            terms_per_numeric = {name: 1 for name in expected_numeric}
        expected_coefficients = sum(terms_per_numeric.values()) + sum(
            len(categorical_levels.get(name, ()))
            for name in feature_order
            if name in CATEGORICAL_FEATURES
        )
        if len(coefficients) != expected_coefficients:
            raise FeatureValidationError(
                "scorer coefficient length does not match feature encoding"
            )
        numeric_values = (
            *numeric_means.values(),
            *numeric_scales.values(),
            *coefficients,
            intercept,
        )
        if any(not math.isfinite(value) for value in numeric_values):
            raise FeatureValidationError("scorer numeric fields must be finite")
        if any(value <= 0 for value in numeric_scales.values()):
            raise FeatureValidationError("scorer numeric scales must be positive")
        scorer = cls(
            feature_order=feature_order,
            numeric_means=numeric_means,
            numeric_scales=numeric_scales,
            categorical_levels=categorical_levels,
            coefficients=coefficients,
            intercept=intercept,
            numeric_encoding=str(numeric_encoding),
            spline_knots=spline_knots,
            spline_degree=spline_degree,
        )
        if payload["required_fields"] != scorer.as_dict()["required_fields"]:
            raise FeatureValidationError("required field contract does not match scorer encoding")
        return scorer


@dataclass(frozen=True, slots=True)
class ModelComparison:
    models: Mapping[str, ModelMetrics]
    selected_model: str
    selection_policy: str
    out_of_fold_probabilities: tuple[float, ...]
    selected_threshold: float
    threshold_capacity: float | int
    operating_capacity: CapacityDecision
    evaluated_prevalence: float
    evaluated_n: int
    split: CrossValidationSummary
    subgroups: Mapping[str, tuple[SubgroupMetrics, ...]]
    cohort_sensitivity: Mapping[str, Mapping[str, float | int | str]]
    paired_differences: Mapping[str, PairedDifference]
    scorer: LogisticScorer
    features: tuple[str, ...]
    intended_use: str
    limitations: tuple[str, ...]
    tuning: Mapping[str, object] = field(default_factory=dict)

    @property
    def brier_score(self) -> float:
        return self.models[self.selected_model].brier_score

    @property
    def pr_auc(self) -> float:
        return self.models[self.selected_model].pr_auc

    def to_artifact(self) -> dict[str, object]:
        """Return aggregate, deterministic JSON content without row-level predictions."""

        return {
            "artifact_schema": "ckd_patient_finding_model_comparison_v2",
            "selected_model": self.selected_model,
            "selection_policy": self.selection_policy,
            "selected_threshold": self.selected_threshold,
            "threshold_capacity": self.threshold_capacity,
            "operating_capacity": {
                "requested_count": self.operating_capacity.requested_count,
                "selected_count": self.operating_capacity.selected_count,
                "selected_share": self.operating_capacity.selected_share,
                "threshold": self.operating_capacity.threshold,
                "tie_policy": self.operating_capacity.tie_policy,
            },
            "evaluated_prevalence": self.evaluated_prevalence,
            "evaluated_n": self.evaluated_n,
            "features": list(self.features),
            "split": asdict(self.split),
            "models": {name: asdict(metrics) for name, metrics in self.models.items()},
            "subgroups": {
                dimension: [asdict(metric) for metric in metrics]
                for dimension, metrics in self.subgroups.items()
            },
            "cohort_sensitivity": self.cohort_sensitivity,
            "paired_differences": {
                name: asdict(difference) for name, difference in self.paired_differences.items()
            },
            "scorer": self.scorer.as_dict(),
            "tuning": dict(self.tuning),
            "intended_use": self.intended_use,
            "limitations": list(self.limitations),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_artifact(), sort_keys=True, indent=2, allow_nan=False) + "\n"


def _looks_like_leakage(column: str) -> bool:
    normalized = column.strip().casefold().replace("-", "_").replace(" ", "_")
    return any(token in normalized for token in LEAKAGE_TOKENS)


def _is_json_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


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

    chosen = (
        list(requested)
        if requested is not None
        else [name for name in PRE_LAB_FEATURES if name in frame.columns]
    )
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
                StandardScaler(),
                numeric,
            ),
            (
                "categorical",
                OneHotEncoder(handle_unknown="error", sparse_output=False),
                categorical,
            ),
        ],
        remainder="drop",
    )
    if kind == "logistic_spline":
        # Cubic B-splines with quantile knots let age, BMI and blood pressure bend;
        # the L2 strength is tuned in the inner loop.
        transformer = ColumnTransformer(
            [
                ("numeric", SplineTransformer(n_knots=5, degree=3, knots="quantile"), numeric),
                (
                    "categorical",
                    OneHotEncoder(handle_unknown="error", sparse_output=False),
                    categorical,
                ),
            ],
            remainder="drop",
        )
        estimator: Any = LogisticRegression(max_iter=LOGISTIC_MAX_ITER, random_state=random_state)
    elif kind == "gradient_boosting":
        estimator = HistGradientBoostingClassifier(
            max_iter=300,
            min_samples_leaf=20,
            early_stopping=False,
            random_state=random_state,
        )
    elif kind == "logistic_regression":
        estimator = LogisticRegression(max_iter=LOGISTIC_MAX_ITER, random_state=random_state)
    elif kind == "random_forest":
        # n_jobs=1: threaded prediction sums trees in a nondeterministic order, which
        # changes the last bits of probabilities between runs and machines.
        estimator = RandomForestClassifier(
            n_estimators=300,
            max_depth=6,
            min_samples_leaf=10,
            random_state=random_state,
            n_jobs=1,
        )
    else:
        raise ValueError(f"unsupported model kind: {kind}")
    return Pipeline([("preprocess", transformer), ("model", estimator)])


def _fit_converged(pipeline: Pipeline, features: pd.DataFrame, y: np.ndarray) -> Pipeline:
    """Fit, treating any optimizer convergence warning as an error.

    A non-converged solver can stop at platform-dependent iterates, so results would
    differ across machines; failing loudly keeps the published numbers reproducible.
    """

    with warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        pipeline.fit(features, y)
    model = pipeline.named_steps["model"]
    if isinstance(model, LogisticRegression) and int(np.max(model.n_iter_)) >= model.max_iter:
        raise FeatureValidationError("logistic regression did not converge")
    return pipeline


@dataclass(frozen=True, slots=True)
class FamilyFit:
    """One tuned model family fitted on a fit set."""

    name: str
    pipeline: Pipeline
    params: dict[str, Any]
    inner_log_loss: float
    inner_log_loss_se: float | None


def _tune_family(
    kind: str,
    columns: Sequence[str],
    features: pd.DataFrame,
    y: np.ndarray,
    groups: pd.Series,
    random_state: int,
    *,
    nested: bool,
) -> FamilyFit:
    """Tune on an inner grouped CV (log loss), then refit the best setting on all rows."""

    frame = features[list(columns)]
    if not nested:
        pipeline = _pipeline(kind, columns, random_state).set_params(**DEFAULT_PARAMS[kind])
        _fit_converged(pipeline, frame, y)
        params = {key.removeprefix("model__"): value for key, value in DEFAULT_PARAMS[kind].items()}
        return FamilyFit(kind, pipeline, params, float("nan"), None)
    inner = StratifiedGroupKFold(n_splits=INNER_SPLITS, shuffle=True, random_state=random_state)
    splits = _validated_grouped_splits(inner, frame, y, groups, context="inner")
    search = GridSearchCV(
        _pipeline(kind, columns, random_state),
        TUNING_GRIDS[kind],
        scoring="neg_log_loss",
        cv=splits,
        error_score="raise",
        refit=False,
        # Candidates are independent fits, so parallelizing them cannot change results.
        n_jobs=-1,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        search.fit(frame, y)
    best = int(search.best_index_)
    losses = np.asarray(
        [-search.cv_results_[f"split{fold}_test_score"][best] for fold in range(INNER_SPLITS)]
    )
    pipeline = _pipeline(kind, columns, random_state).set_params(**search.best_params_)
    _fit_converged(pipeline, frame, y)
    return FamilyFit(
        name=kind,
        pipeline=pipeline,
        params={key.removeprefix("model__"): value for key, value in search.best_params_.items()},
        inner_log_loss=float(losses.mean()),
        inner_log_loss_se=float(losses.std(ddof=1) / math.sqrt(len(losses))),
    )


def select_family(fits: Mapping[str, FamilyFit]) -> str:
    """One-standard-error rule: the simplest family within one SE of the best inner loss."""

    best = min(fits.values(), key=lambda fit: fit.inner_log_loss)
    if best.inner_log_loss_se is None or not math.isfinite(best.inner_log_loss):
        return MODEL_FAMILIES[0]
    limit = best.inner_log_loss + best.inner_log_loss_se
    return next(
        name for name in MODEL_FAMILIES if name in fits and fits[name].inner_log_loss <= limit
    )


def _fit_record(fit: FamilyFit) -> dict[str, Any]:
    grid = {key.removeprefix("model__"): values for key, values in TUNING_GRIDS[fit.name].items()}
    return {
        "params": dict(fit.params),
        "inner_log_loss": fit.inner_log_loss if math.isfinite(fit.inner_log_loss) else None,
        "inner_log_loss_se": fit.inner_log_loss_se,
        "params_at_grid_edge": sorted(
            name
            for name, value in fit.params.items()
            if len(grid[name]) > 1 and value in (grid[name][0], grid[name][-1])
        ),
    }


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


def _percentile_interval(
    values: Sequence[float], *, requested: int, cluster_count: int
) -> UncertaintyInterval:
    valid = np.asarray([value for value in values if math.isfinite(value)], dtype=float)
    if len(valid) == 0:
        raise FeatureValidationError("cluster bootstrap produced no valid replicates")
    caveats: list[str] = []
    if cluster_count < 20:
        caveats.append(f"Only {cluster_count} clusters; interval precision is limited.")
    if len(valid) < max(20, int(0.8 * requested)):
        caveats.append(f"Only {len(valid)} of {requested} bootstrap replicates were estimable.")
    low, high = np.percentile(valid, [2.5, 97.5])
    return UncertaintyInterval(
        low=float(low),
        high=float(high),
        method="cluster_bootstrap_percentile",
        requested_replicates=requested,
        valid_replicates=int(len(valid)),
        cluster_count=cluster_count,
        caveat=" ".join(caveats) or None,
    )


def _bootstrap_indices(
    groups: np.ndarray, *, replicates: int, random_state: int
) -> list[np.ndarray]:
    if replicates < 20:
        raise ValueError("bootstrap_replicates must be at least 20")
    unique = np.asarray(sorted(set(str(value) for value in groups)), dtype=object)
    if len(unique) < 2:
        raise FeatureValidationError("at least two clusters are required for uncertainty")
    positions = {group: np.flatnonzero(groups.astype(str) == group) for group in unique}
    rng = np.random.default_rng(random_state)
    output: list[np.ndarray] = []
    for _ in range(replicates):
        sampled = rng.choice(unique, size=len(unique), replace=True)
        output.append(np.concatenate([positions[str(group)] for group in sampled]))
    return output


def select_capacity_decision(
    probabilities: Sequence[float], capacity: float | int
) -> CapacityDecision:
    """Select exactly the allowed count with a deterministic tie-break.

    Fractional capacity is rounded to the nearest whole observation for the current
    sample, with a minimum of one and a maximum of the sample size.
    """

    values = np.asarray(probabilities, dtype=float)
    if len(values) == 0 or not np.isfinite(values).all():
        raise ValueError("probabilities must be a nonempty finite sequence")
    count = _capacity_count(len(values), capacity)
    stable_position = np.arange(len(values))
    order = np.lexsort((stable_position, -values))
    selected = np.zeros(len(values), dtype=bool)
    selected[order[:count]] = True
    threshold = float(values[order[count - 1]])
    return CapacityDecision(
        selected=tuple(bool(value) for value in selected),
        threshold=threshold,
        requested_count=count,
        selected_count=int(selected.sum()),
        selected_share=float(selected.mean()),
        tie_policy="descending_probability_then_stable_row_order",
    )


def _metric_intervals(
    y: np.ndarray,
    probabilities: np.ndarray,
    groups: np.ndarray,
    capacity: float | int,
    *,
    replicates: int,
    random_state: int,
) -> dict[str, UncertaintyInterval | None]:
    samples = _bootstrap_indices(groups, replicates=replicates, random_state=random_state)
    values: dict[str, list[float]] = {
        "roc_auc": [],
        "pr_auc": [],
        "brier": [],
        "precision": [],
        "recall": [],
    }
    for positions in samples:
        sample_y = y[positions]
        sample_p = probabilities[positions]
        sample_decision = select_capacity_decision(sample_p.tolist(), capacity)
        sample_predicted = np.asarray(sample_decision.selected, dtype=bool)
        if len(np.unique(sample_y)) == 2:
            values["roc_auc"].append(float(roc_auc_score(sample_y, sample_p)))
            values["pr_auc"].append(float(average_precision_score(sample_y, sample_p)))
        values["brier"].append(float(brier_score_loss(sample_y, sample_p)))
        if int(sample_predicted.sum()) > 0:
            values["precision"].append(
                float(precision_score(sample_y, sample_predicted, zero_division=0))
            )
        if int(sample_y.sum()) > 0:
            values["recall"].append(
                float(recall_score(sample_y, sample_predicted, zero_division=0))
            )
    clusters = len(set(str(value) for value in groups))
    return {
        name: (
            _percentile_interval(metric_values, requested=replicates, cluster_count=clusters)
            if metric_values
            else None
        )
        for name, metric_values in values.items()
    }


def _required_interval(
    intervals: Mapping[str, UncertaintyInterval | None], name: str
) -> UncertaintyInterval:
    interval = intervals[name]
    if interval is None:
        raise FeatureValidationError(f"{name} uncertainty could not be estimated")
    return interval


def _metrics(
    y: np.ndarray,
    probabilities: np.ndarray,
    groups: np.ndarray,
    capacity: float | int,
    *,
    replicates: int,
    random_state: int,
) -> ModelMetrics:
    decision = select_capacity_decision(probabilities.tolist(), capacity)
    predicted = np.asarray(decision.selected, dtype=bool)
    matrix = confusion_matrix(y, predicted, labels=[0, 1])
    tn, fp, fn, tp = (int(value) for value in matrix.ravel())
    roc = float(roc_auc_score(y, probabilities)) if len(np.unique(y)) == 2 else float("nan")
    pr = float(average_precision_score(y, probabilities)) if int(y.sum()) > 0 else float("nan")
    intervals = _metric_intervals(
        y,
        probabilities,
        groups,
        capacity,
        replicates=replicates,
        random_state=random_state,
    )
    return ModelMetrics(
        roc_auc=roc,
        pr_auc=pr,
        brier_score=float(brier_score_loss(y, probabilities)),
        precision=float(precision_score(y, predicted, zero_division=0)),
        recall=float(recall_score(y, predicted, zero_division=0)),
        threshold=decision.threshold,
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
        requested_count=decision.requested_count,
        selected_count=decision.selected_count,
        selected_share=decision.selected_share,
        tie_policy=decision.tie_policy,
        roc_auc_interval=_required_interval(intervals, "roc_auc"),
        pr_auc_interval=_required_interval(intervals, "pr_auc"),
        brier_interval=_required_interval(intervals, "brier"),
        precision_interval=_required_interval(intervals, "precision"),
        recall_interval=_required_interval(intervals, "recall"),
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
    """Return the out-of-fold boundary only when it uniquely encodes exact capacity.

    A scalar threshold cannot express a partial selection among equal probabilities.
    Call :func:`select_capacity_decision` when a deterministic exact-capacity mask is
    required.
    """

    decision = select_capacity_decision(report.out_of_fold_probabilities, capacity)
    values = np.asarray(report.out_of_fold_probabilities, dtype=float)
    scalar_selected_count = int((values >= decision.threshold).sum())
    if scalar_selected_count != decision.requested_count:
        raise CapacityBoundaryError(
            "boundary probability is tied; use select_capacity_decision for the "
            "exact-capacity ranked mask"
        )
    return decision.threshold


def _subgroups(
    evaluated: pd.DataFrame,
    y: np.ndarray,
    probabilities: np.ndarray,
    selected: np.ndarray,
    groups: np.ndarray,
    capacity: float | int,
    *,
    replicates: int,
    random_state: int,
) -> dict[str, tuple[SubgroupMetrics, ...]]:
    age = pd.to_numeric(evaluated["age_years"], errors="coerce")
    dimensions: dict[str, pd.Series] = {
        "age_band": pd.cut(
            age,
            bins=[17, 39, 59, 120],
            labels=["18-39", "40-59", "60+"],
            include_lowest=True,
        ).astype("string"),
        "sex": evaluated["sex"].astype("string"),
    }
    for name in ("race_ethnicity", "diabetes_history", "hypertension_history"):
        if name in evaluated:
            dimensions[name] = evaluated[name].astype("string")
    output: dict[str, tuple[SubgroupMetrics, ...]] = {}
    for dimension, values in dimensions.items():
        records: list[SubgroupMetrics] = []
        for value in sorted(values.dropna().unique()):
            mask = values.eq(value).fillna(False).to_numpy(dtype=bool)
            group_y = y[mask]
            group_p = probabilities[mask]
            group_selected = selected[mask]
            group_clusters = groups[mask]
            positives = int(group_y.sum())
            caveats: list[str] = []
            if len(group_y) < 30 or positives < 20 or len(group_y) - positives < 20:
                caveats.append(
                    "Sparse subgroup (fewer than 20 events or non-events, or fewer "
                    "than 30 records); metrics are descriptive and potentially unstable."
                )
            predicted = group_selected
            if int(predicted.sum()) == 0:
                caveats.append(
                    "No records were flagged by the exact-capacity "
                    "ranked mask; precision is undefined."
                )
            subgroup_cluster_count = len(set(str(item) for item in group_clusters))
            sparse = (
                len(group_y) < 30
                or positives < 20
                or len(group_y) - positives < 20
                or subgroup_cluster_count < 2
            )
            if subgroup_cluster_count < 2:
                caveats.append(
                    "Fewer than two contributing clusters; uncertainty intervals are unavailable."
                )
            elif sparse:
                caveats.append("Sparse subgroup; uncertainty intervals are unavailable.")
            intervals = (
                _subgroup_metric_intervals(
                    y,
                    probabilities,
                    groups,
                    values.to_numpy(dtype=object),
                    value,
                    capacity,
                    replicates=replicates,
                    random_state=random_state + len(records),
                )
                if not sparse
                else {"precision": None, "recall": None, "brier": None}
            )
            if int(predicted.sum()) == 0:
                intervals["precision"] = None
            if positives == 0:
                intervals["recall"] = None
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
                    precision_interval=intervals["precision"],
                    recall_interval=intervals["recall"],
                    brier_interval=intervals["brier"],
                    caveat=" ".join(caveats) or None,
                    roc_auc=(
                        float(roc_auc_score(group_y, group_p))
                        if 0 < positives < len(group_y)
                        else None
                    ),
                    mean_probability=float(group_p.mean()),
                    flagged_share=float(predicted.mean()),
                )
            )
        output[dimension] = tuple(records)
    return output


def _subgroup_metric_intervals(
    y: np.ndarray,
    probabilities: np.ndarray,
    groups: np.ndarray,
    subgroup_values: np.ndarray,
    subgroup_value: object,
    capacity: float | int,
    *,
    replicates: int,
    random_state: int,
) -> dict[str, UncertaintyInterval | None]:
    """Bootstrap the full evaluated set, rerank capacity, then measure one subgroup."""

    original_mask = subgroup_values == subgroup_value
    subgroup_clusters = len(set(str(item) for item in groups[original_mask]))
    if subgroup_clusters < 2:
        return {"precision": None, "recall": None, "brier": None}

    samples = _bootstrap_indices(groups, replicates=replicates, random_state=random_state)
    values: dict[str, list[float]] = {"precision": [], "recall": [], "brier": []}
    for positions in samples:
        sample_y = y[positions]
        sample_p = probabilities[positions]
        sample_subgroup = subgroup_values[positions] == subgroup_value
        if not bool(sample_subgroup.any()):
            continue
        decision = select_capacity_decision(sample_p.tolist(), capacity)
        sample_selected = np.asarray(decision.selected, dtype=bool)[sample_subgroup]
        subgroup_y = sample_y[sample_subgroup]
        subgroup_p = sample_p[sample_subgroup]
        values["brier"].append(float(brier_score_loss(subgroup_y, subgroup_p)))
        if int(sample_selected.sum()) > 0:
            values["precision"].append(
                float(precision_score(subgroup_y, sample_selected, zero_division=0))
            )
        if int(subgroup_y.sum()) > 0:
            values["recall"].append(
                float(recall_score(subgroup_y, sample_selected, zero_division=0))
            )

    return {
        name: (
            _percentile_interval(
                metric_values,
                requested=replicates,
                cluster_count=subgroup_clusters,
            )
            if metric_values
            else None
        )
        for name, metric_values in values.items()
    }


def _portable_scorer(
    pipeline: Pipeline, features: Sequence[str], training: pd.DataFrame
) -> LogisticScorer:
    preprocess: ColumnTransformer = pipeline.named_steps["preprocess"]
    model: LogisticRegression = pipeline.named_steps["model"]
    numeric = [name for name in features if name in NUMERIC_FEATURES]
    categorical = [name for name in features if name in CATEGORICAL_FEATURES]
    numeric_step = preprocess.named_transformers_["numeric"]
    encoder: OneHotEncoder = preprocess.named_transformers_["categorical"]
    if isinstance(numeric_step, SplineTransformer):
        means = {name: float(training[name].mean()) for name in numeric}
        scales = {name: float(training[name].std(ddof=0)) for name in numeric}
        encoding = "cubic_bspline"
        knots = {
            name: tuple(float(knot) for knot in spline.t)
            for name, spline in zip(numeric, numeric_step.bsplines_, strict=True)
        }
        degree = int(numeric_step.degree)
    else:
        scaler = cast(StandardScaler, numeric_step)
        means = {name: float(value) for name, value in zip(numeric, scaler.mean_, strict=True)}
        scales = {name: float(value) for name, value in zip(numeric, scaler.scale_, strict=True)}
        encoding, knots, degree = "standardize", {}, 3
    return LogisticScorer(
        feature_order=tuple(features),
        numeric_means=means,
        numeric_scales=scales,
        categorical_levels={
            name: tuple(str(value) for value in levels)
            for name, levels in zip(categorical, encoder.categories_, strict=True)
        },
        coefficients=tuple(float(value) for value in model.coef_[0]),
        intercept=float(model.intercept_[0]),
        numeric_encoding=encoding,
        spline_knots=knots,
        spline_degree=degree,
    )


def _validate_training_features(features: pd.DataFrame) -> pd.DataFrame:
    validated = features.copy()
    for name in validated:
        if name in NUMERIC_FEATURES:
            values = pd.to_numeric(validated[name], errors="coerce")
            if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
                raise FeatureValidationError(f"{name} must be complete, numeric, and finite")
            lower, upper = _numeric_range(name)
            if bool((~values.between(lower, upper)).any()):
                raise FeatureValidationError(f"{name} must be between {lower:g} and {upper:g}")
            validated[name] = values.astype(float)
        else:
            if validated[name].isna().any():
                raise FeatureValidationError(f"{name} must be complete")
            values = validated[name].astype("string").str.strip()
            if bool(values.eq("").any()):
                raise FeatureValidationError(f"{name} must contain nonempty categories")
            validated[name] = values
    return validated


def _validated_grouped_splits(
    splitter: StratifiedGroupKFold,
    features: pd.DataFrame,
    y: np.ndarray,
    groups: pd.Series,
    *,
    context: str,
) -> list[tuple[np.ndarray, np.ndarray]]:
    for outcome_class in (0, 1):
        class_group_count = int(groups.loc[y == outcome_class].nunique())
        if class_group_count < splitter.n_splits:
            raise FeatureValidationError(
                f"{context} folds must contain both outcome classes; class "
                f"{outcome_class} occurs in only {class_group_count} groups"
            )
    splits = list(splitter.split(features, y, groups))
    for fold, (fit_index, score_index) in enumerate(splits, start=1):
        if len(np.unique(y[fit_index])) != 2 or len(np.unique(y[score_index])) != 2:
            raise FeatureValidationError(
                f"{context} fold {fold} must contain both outcome classes in fit and score sets"
            )
        fit_groups = set(groups.iloc[fit_index].astype(str))
        score_groups = set(groups.iloc[score_index].astype(str))
        if not fit_groups.isdisjoint(score_groups):
            raise FeatureValidationError(f"{context} fold {fold} leaks groups")
    return splits


def _paired_metric_differences(
    y: np.ndarray,
    first: np.ndarray,
    second: np.ndarray,
    groups: np.ndarray,
    *,
    first_name: str,
    second_name: str,
    replicates: int,
    random_state: int,
) -> dict[str, PairedDifference]:
    """Paired cluster-bootstrap differences ``first - second`` on the same predictions."""

    metrics: dict[str, Callable[[np.ndarray, np.ndarray], float]] = {
        "roc_auc": lambda truth, score: float(roc_auc_score(truth, score)),
        "pr_auc": lambda truth, score: float(average_precision_score(truth, score)),
        "brier_score": lambda truth, score: float(brier_score_loss(truth, score)),
    }
    bootstraps = _bootstrap_indices(groups, replicates=replicates, random_state=random_state)
    cluster_count = len(set(str(value) for value in groups))
    output: dict[str, PairedDifference] = {}
    for metric, calculate in metrics.items():
        estimate = calculate(y, first) - calculate(y, second)
        values = [
            calculate(y[positions], first[positions]) - calculate(y[positions], second[positions])
            for positions in bootstraps
            if len(np.unique(y[positions])) == 2
        ]
        interval = _percentile_interval(values, requested=replicates, cluster_count=cluster_count)
        if interval.low <= 0 <= interval.high:
            interpretation = "Interval includes zero; no reliable difference is established."
        elif metric == "brier_score":
            interpretation = (
                f"{first_name} has lower error."
                if interval.high < 0
                else f"{second_name} has lower error."
            )
        else:
            interpretation = (
                f"{first_name} has higher discrimination."
                if interval.low > 0
                else f"{second_name} has higher discrimination."
            )
        output[metric] = PairedDifference(
            metric=metric,
            comparison=f"{first_name} minus {second_name}",
            estimate=float(estimate),
            interval=interval,
            interpretation=interpretation,
        )
    return output


def _validated_sensitivity_target(train: pd.DataFrame, name: str) -> np.ndarray | None:
    if name not in train:
        return None
    values = pd.to_numeric(train[name], errors="coerce")
    if values.isna().any():
        raise FeatureValidationError("cohort sensitivity must use the common complete-case domain")
    if not set(values.unique()).issubset({0, 1}):
        raise FeatureValidationError("sensitivity outcomes must be binary")
    return values.astype(int).to_numpy()


def train_patient_finding_models(
    train: pd.DataFrame,
    groups: Sequence[object] | pd.Series,
    *,
    capacity: float | int = 0.10,
    random_state: int = 20260910,
    target_column: str = "ckd_indicator",
    bootstrap_replicates: int = 200,
    n_splits: int = 5,
    nested_selection: bool = False,
) -> ModelComparison:
    """Select and evaluate a screening model with nested grouped cross-validation.

    Survey clusters never appear in both the fitting and the scoring folds, and every
    person receives exactly one out-of-fold prediction. With ``nested_selection`` each
    outer fit set tunes every family in :data:`MODEL_FAMILIES` on an inner grouped CV
    and picks one by :data:`SELECTION_RULE`; the outer scoring fold then measures that
    whole procedure, so the reported estimate is not inflated by the choice. The same
    procedure run on the full cohort picks the deployed model. Without it (fixture
    runs and fast tests) logistic regression and a random forest are fitted at fixed
    settings and logistic regression is reported. A demographics-only logistic model
    and a constant-prevalence score are evaluated on the same folds as baselines.
    """

    if target_column != "ckd_indicator":
        raise LeakageError("target is the fixed laboratory indicator documented for this task")
    if target_column not in train:
        raise FeatureValidationError(f"missing target column: {target_column}")
    if len(train) != len(groups):
        raise FeatureValidationError("groups must have one value per training row")
    y_series = pd.to_numeric(train[target_column], errors="coerce")
    if y_series.isna().any() or not set(y_series.unique()).issubset({0, 1}):
        raise FeatureValidationError("target must be complete and binary")
    if y_series.nunique() < 2:
        raise FeatureValidationError("target must contain both outcome classes")
    sensitivity_targets = {
        name: _validated_sensitivity_target(train, name)
        for name in ("sensitivity_egfr_only", "sensitivity_albuminuria_only")
    }
    group_series = pd.Series(groups, index=train.index, dtype="string")
    if group_series.isna().any() or group_series.nunique() < 10:
        raise FeatureValidationError("at least ten complete groups are required")

    features = _validate_training_features(build_pre_lab_features(train))
    if not set(DEMOGRAPHIC_FEATURES).issubset(features.columns):
        raise FeatureValidationError("age_years, sex, and race_ethnicity are required")
    feature_names = list(features.columns)
    y = y_series.astype(int).to_numpy()
    group_array = group_series.astype(str).to_numpy()

    splitter = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=random_state)
    folds = _validated_grouped_splits(splitter, features, y, group_series, context="outer")

    families = MODEL_FAMILIES if nested_selection else ("logistic_regression", "random_forest")
    has_clinical_features = set(feature_names) != set(DEMOGRAPHIC_FEATURES)
    demographic_columns = [name for name in feature_names if name in DEMOGRAPHIC_FEATURES]
    baselines = [DEMOGRAPHICS_MODEL] if has_clinical_features else []
    out_of_fold = {name: np.zeros(len(y), dtype=float) for name in [*families, *baselines]}
    selected_oof = np.zeros(len(y), dtype=float)
    fold_records: list[dict[str, Any]] = []
    for fit_index, score_index in folds:
        fit_features = features.iloc[fit_index].reset_index(drop=True)
        fit_groups = group_series.iloc[fit_index].reset_index(drop=True)
        fits = {
            name: _tune_family(
                name,
                feature_names,
                fit_features,
                y[fit_index],
                fit_groups,
                random_state,
                nested=nested_selection,
            )
            for name in families
        }
        chosen = select_family(fits) if nested_selection else "logistic_regression"
        for name, fit in fits.items():
            out_of_fold[name][score_index] = fit.pipeline.predict_proba(
                features.iloc[score_index][feature_names]
            )[:, 1]
        selected_oof[score_index] = out_of_fold[chosen][score_index]
        if has_clinical_features:
            baseline = _fit_converged(
                _pipeline("logistic_regression", demographic_columns, random_state),
                features.iloc[fit_index][demographic_columns],
                y[fit_index],
            )
            out_of_fold[DEMOGRAPHICS_MODEL][score_index] = baseline.predict_proba(
                features.iloc[score_index][demographic_columns]
            )[:, 1]
        fold_records.append(
            {"selected": chosen, "families": {name: _fit_record(fit) for name, fit in fits.items()}}
        )

    final_fits = {
        name: _tune_family(
            name,
            feature_names,
            features.reset_index(drop=True),
            y,
            group_series.reset_index(drop=True),
            random_state,
            nested=nested_selection,
        )
        for name in families
    }
    selected_model = select_family(final_fits) if nested_selection else "logistic_regression"
    if selected_model not in SCORER_FAMILIES:
        raise FeatureValidationError(
            f"selected family {selected_model} has no portable JSON scorer; "
            "export support must be added before it can be deployed"
        )
    scorer = _portable_scorer(final_fits[selected_model].pipeline, feature_names, features)

    # Headline scores: the selected family, tuned inside each outer fold. The
    # nested_selection row (family re-chosen inside each outer fold) is the
    # conservative estimate of the whole selection procedure.
    logistic = out_of_fold[selected_model]
    operating = select_capacity_decision(logistic.tolist(), capacity)
    # A constant score at the cohort prevalence: ROC-AUC 0.5, PR-AUC equal to prevalence
    # and Brier score p(1 - p) by construction.
    no_skill = np.full(len(y), float(y.mean()), dtype=float)
    evaluated = {"prevalence_no_skill": no_skill, **out_of_fold}
    if nested_selection:
        evaluated[NESTED_SELECTION_MODEL] = selected_oof
    metrics = {
        name: _metrics(
            y,
            probabilities,
            group_array,
            capacity,
            replicates=bootstrap_replicates,
            random_state=random_state + 10 * (position + 1),
        )
        for position, (name, probabilities) in enumerate(evaluated.items())
    }

    sensitivity: dict[str, Mapping[str, float | int | str]] = {
        "primary_definition": {
            "target": target_column,
            "evaluated_n": int(len(y)),
            "evaluated_prevalence": float(y.mean()),
        }
    }
    for name, alternative in sensitivity_targets.items():
        if alternative is not None and len(np.unique(alternative)) == 2:
            sensitivity[name] = {
                "evaluated_n": int(len(alternative)),
                "evaluated_prevalence": float(alternative.mean()),
                "roc_auc": float(roc_auc_score(alternative, logistic)),
                "pr_auc": float(average_precision_score(alternative, logistic)),
            }

    paired: dict[str, PairedDifference] = {}
    # The selected family's out-of-fold scores against every alternative, paired on
    # the same bootstrap replicates: is any rival reliably better than it?
    rivals = [name for name in [*families, *baselines] if name != selected_model]
    for offset, other in enumerate(rivals):
        differences = _paired_metric_differences(
            y,
            logistic,
            out_of_fold[other],
            group_array,
            first_name=selected_model,
            second_name=other,
            replicates=bootstrap_replicates,
            random_state=random_state + 50 + offset,
        )
        paired.update(
            {
                f"{selected_model}_minus_{other}_{metric}": value
                for metric, value in differences.items()
            }
        )

    return ModelComparison(
        models=metrics,
        selected_model=selected_model,
        selection_policy=(
            "nested_grouped_cv_one_standard_error_rule"
            if nested_selection
            else "fixed_logistic_without_nested_selection"
        ),
        out_of_fold_probabilities=tuple(float(value) for value in logistic),
        selected_threshold=operating.threshold,
        threshold_capacity=capacity,
        operating_capacity=operating,
        evaluated_prevalence=float(y.mean()),
        evaluated_n=int(len(y)),
        split=CrossValidationSummary(
            strategy=(
                f"stratified grouped {n_splits}-fold cross-validation; survey clusters "
                "never shared between fitting and scoring folds; pooled out-of-fold "
                "predictions"
            ),
            folds=n_splits,
            evaluated_n=int(len(y)),
            group_count=int(group_series.nunique()),
            scoring_fold_sizes=tuple(int(len(score)) for _, score in folds),
            scoring_fold_group_counts=tuple(
                int(group_series.iloc[score].nunique()) for _, score in folds
            ),
            threshold_source="pooled_out_of_fold_selected_model_predictions",
            random_state=random_state,
        ),
        subgroups=_subgroups(
            features,
            y,
            logistic,
            np.asarray(operating.selected, dtype=bool),
            group_array,
            capacity,
            replicates=bootstrap_replicates,
            random_state=random_state + 40,
        ),
        cohort_sensitivity=sensitivity,
        paired_differences=paired,
        scorer=scorer,
        tuning={
            "rule": SELECTION_RULE if nested_selection else "no nested selection (fixed settings)",
            "grids": {
                name: {key.removeprefix("model__"): values for key, values in grid.items()}
                for name, grid in TUNING_GRIDS.items()
                if name in families
            },
            "outer_folds": fold_records,
            "full_cohort": {
                "selected": selected_model,
                "families": {name: _fit_record(fit) for name, fit in final_fits.items()},
            },
        },
        features=tuple(feature_names),
        intended_use=(
            "Educational comparison of population-level screening opportunity; "
            "not a diagnosis or clinical decision tool."
        ),
        limitations=(
            "Cross-sectional NHANES laboratory indicators cannot confirm chronic disease.",
            "Performance metrics are unweighted and describe this analytic cohort, "
            "not U.S. population performance.",
            "Intervals resample survey clusters with the fitted fold models held fixed; "
            "they do not include model-refitting variability.",
            "Subgroup metrics are descriptive; small event counts can be unstable.",
        ),
    )
