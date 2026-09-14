"""Leakage-safe screening-opportunity model comparison.

This module supports an educational population-analytics demonstration. It does not
diagnose CKD, recommend care, or identify patients for clinical action.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, cast

import numpy as np
import pandas as pd
from sklearn.base import clone  # type: ignore[import-untyped]
from sklearn.compose import ColumnTransformer  # type: ignore[import-untyped]
from sklearn.ensemble import RandomForestClassifier  # type: ignore[import-untyped]
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


@dataclass(frozen=True, slots=True)
class PairedDifference:
    metric: str
    comparison: str
    estimate: float
    interval: UncertaintyInterval
    interpretation: str


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
    numeric_means: Mapping[str, float]
    numeric_scales: Mapping[str, float]
    categorical_levels: Mapping[str, tuple[str, ...]]
    coefficients: tuple[float, ...]
    intercept: float
    artifact_version: str = "1.0.0"
    missing_value_policy: str = "reject"
    unknown_category_policy: str = "reject"
    coefficient_precision: str = "float64"

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
        if linear >= 0:
            return float(1.0 / (1.0 + math.exp(-linear)))
        exponential = math.exp(linear)
        return float(exponential / (1.0 + exponential))

    def as_dict(self) -> dict[str, object]:
        return {
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
        expected_categorical = {
            name for name in feature_order if name in CATEGORICAL_FEATURES
        }
        if set(categorical_levels) != expected_categorical or any(
            not levels or len(set(levels)) != len(levels)
            for levels in categorical_levels.values()
        ):
            raise FeatureValidationError(
                "scorer categorical levels do not match feature_order"
            )
        expected_coefficients = sum(name in NUMERIC_FEATURES for name in feature_order) + sum(
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
        )
        if payload["required_fields"] != scorer.as_dict()["required_fields"]:
            raise FeatureValidationError("required field contract does not match scorer encoding")
        return scorer


@dataclass(frozen=True, slots=True)
class ModelComparison:
    models: Mapping[str, ModelMetrics]
    selected_model: str
    selection_policy: str
    selection_probabilities: tuple[float, ...]
    holdout_probabilities: tuple[float, ...]
    selected_threshold: float
    threshold_capacity: float | int
    development_capacity: CapacityDecision
    holdout_prevalence: float
    holdout_n: int
    split: SplitSummary
    subgroups: Mapping[str, tuple[SubgroupMetrics, ...]]
    cohort_sensitivity: Mapping[str, Mapping[str, float | int | str]]
    paired_differences: Mapping[str, PairedDifference]
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
            "selection_policy": self.selection_policy,
            "selected_threshold": self.selected_threshold,
            "threshold_capacity": self.threshold_capacity,
            "development_capacity": {
                "requested_count": self.development_capacity.requested_count,
                "selected_count": self.development_capacity.selected_count,
                "selected_share": self.development_capacity.selected_share,
                "threshold": self.development_capacity.threshold,
                "tie_policy": self.development_capacity.tie_policy,
            },
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
            "paired_differences": {
                name: asdict(difference)
                for name, difference in self.paired_differences.items()
            },
            "scorer": self.scorer.as_dict(),
            "intended_use": self.intended_use,
            "limitations": list(self.limitations),
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_artifact(), sort_keys=True, indent=2, allow_nan=False
        ) + "\n"


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


def _percentile_interval(
    values: Sequence[float], *, requested: int, cluster_count: int
) -> UncertaintyInterval:
    valid = np.asarray([value for value in values if math.isfinite(value)], dtype=float)
    if len(valid) == 0:
        raise FeatureValidationError("cluster bootstrap produced no valid replicates")
    caveats: list[str] = []
    if cluster_count < 20:
        caveats.append(
            f"Only {cluster_count} holdout clusters; interval precision is limited."
        )
    if len(valid) < max(20, int(0.8 * requested)):
        caveats.append(
            f"Only {len(valid)} of {requested} bootstrap replicates were estimable."
        )
    low, high = np.percentile(valid, [2.5, 97.5])
    return UncertaintyInterval(
        low=float(low),
        high=float(high),
        method="holdout_cluster_bootstrap_percentile",
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
    pr = (
        float(average_precision_score(y, probabilities))
        if int(y.sum()) > 0
        else float("nan")
    )
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
    """Return the development boundary only when it uniquely encodes exact capacity.

    A scalar threshold cannot express a partial selection among equal probabilities.
    Call :func:`select_capacity_decision` when a deterministic exact-capacity mask is
    required.
    """

    decision = select_capacity_decision(report.selection_probabilities, capacity)
    values = np.asarray(report.selection_probabilities, dtype=float)
    scalar_selected_count = int((values >= decision.threshold).sum())
    if scalar_selected_count != decision.requested_count:
        raise CapacityBoundaryError(
            "boundary probability is tied; use select_capacity_decision for the "
            "exact-capacity ranked mask"
        )
    return decision.threshold


def _subgroups(
    holdout: pd.DataFrame,
    y: np.ndarray,
    probabilities: np.ndarray,
    selected: np.ndarray,
    groups: np.ndarray,
    capacity: float | int,
    *,
    replicates: int,
    random_state: int,
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
                    "No records were flagged by the holdout-specific exact-capacity "
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
                    "Fewer than two contributing clusters; uncertainty intervals "
                    "are unavailable."
                )
            elif sparse:
                caveats.append(
                    "Sparse subgroup; uncertainty intervals are unavailable."
                )
            intervals = _subgroup_metric_intervals(
                y,
                probabilities,
                groups,
                values.to_numpy(dtype=object),
                value,
                capacity,
                replicates=replicates,
                random_state=random_state + len(records),
            ) if not sparse else {"precision": None, "recall": None, "brier": None}
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
    """Bootstrap the full holdout, rerank capacity, then measure one subgroup."""

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


def _portable_scorer(pipeline: Pipeline, features: Sequence[str]) -> LogisticScorer:
    preprocess: ColumnTransformer = pipeline.named_steps["preprocess"]
    model: LogisticRegression = pipeline.named_steps["model"]
    numeric = [name for name in features if name in NUMERIC_FEATURES]
    categorical = [name for name in features if name in CATEGORICAL_FEATURES]
    scaler: StandardScaler = preprocess.named_transformers_["numeric"]
    encoder: OneHotEncoder = preprocess.named_transformers_["categorical"]
    return LogisticScorer(
        feature_order=tuple(features),
        numeric_means={
            name: float(value) for name, value in zip(numeric, scaler.mean_, strict=True)
        },
        numeric_scales={
            name: float(value) for name, value in zip(numeric, scaler.scale_, strict=True)
        },
        categorical_levels={
            name: tuple(str(value) for value in levels)
            for name, levels in zip(categorical, encoder.categories_, strict=True)
        },
        coefficients=tuple(float(value) for value in model.coef_[0]),
        intercept=float(model.intercept_[0]),
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
                raise FeatureValidationError(
                    f"{name} must be between {lower:g} and {upper:g}"
                )
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
    logistic: np.ndarray,
    forest: np.ndarray,
    groups: np.ndarray,
    *,
    replicates: int,
    random_state: int,
) -> dict[str, PairedDifference]:
    specifications: dict[
        str,
        tuple[
            float,
            Callable[[np.ndarray, np.ndarray, np.ndarray], float],
        ],
    ] = {
        "roc_auc": (
            float(roc_auc_score(y, logistic) - roc_auc_score(y, forest)),
            lambda truth, first, second: float(
                roc_auc_score(truth, first) - roc_auc_score(truth, second)
            ),
        ),
        "pr_auc": (
            float(average_precision_score(y, logistic) - average_precision_score(y, forest)),
            lambda truth, first, second: float(
                average_precision_score(truth, first)
                - average_precision_score(truth, second)
            ),
        ),
        "brier_score": (
            float(brier_score_loss(y, logistic) - brier_score_loss(y, forest)),
            lambda truth, first, second: float(
                brier_score_loss(truth, first) - brier_score_loss(truth, second)
            ),
        ),
    }
    bootstraps = _bootstrap_indices(
        groups, replicates=replicates, random_state=random_state
    )
    output: dict[str, PairedDifference] = {}
    for metric, (estimate, calculate) in specifications.items():
        values: list[float] = []
        for positions in bootstraps:
            sample_y = y[positions]
            if len(np.unique(sample_y)) != 2:
                continue
            values.append(calculate(sample_y, logistic[positions], forest[positions]))
        interval = _percentile_interval(
            values,
            requested=replicates,
            cluster_count=len(set(str(value) for value in groups)),
        )
        interval = UncertaintyInterval(
            low=min(interval.low, estimate),
            high=max(interval.high, estimate),
            method=interval.method,
            requested_replicates=interval.requested_replicates,
            valid_replicates=interval.valid_replicates,
            cluster_count=interval.cluster_count,
            caveat=interval.caveat,
        )
        if interval.low <= 0 <= interval.high:
            interpretation = "Interval includes zero; no reliable model advantage is established."
        elif metric == "brier_score":
            interpretation = (
                "Logistic regression has lower error."
                if interval.high < 0
                else "Random forest has lower error."
            )
        else:
            interpretation = (
                "Logistic regression has higher discrimination."
                if interval.low > 0
                else "Random forest has higher discrimination."
            )
        key = f"logistic_minus_random_forest_{metric}"
        output[key] = PairedDifference(
            metric=metric,
            comparison="logistic_regression minus random_forest",
            estimate=estimate,
            interval=interval,
            interpretation=interpretation,
        )
    return output


def train_patient_finding_models(
    train: pd.DataFrame,
    groups: Sequence[object] | pd.Series,
    *,
    capacity: float | int = 0.10,
    random_state: int = 20260910,
    target_column: str = "ckd_indicator",
    bootstrap_replicates: int = 200,
) -> ModelComparison:
    """Compare no-skill, logistic, and tree models with a group-isolated holdout."""

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
    for alternative in ("sensitivity_egfr_only", "sensitivity_albuminuria_only"):
        if alternative in train:
            values = pd.to_numeric(train[alternative], errors="coerce")
            if values.isna().any():
                raise FeatureValidationError(
                    "cohort sensitivity must use the common complete-case domain"
                )
            if not set(values.unique()).issubset({0, 1}):
                raise FeatureValidationError("sensitivity outcomes must be binary")
    group_series = pd.Series(groups, index=train.index, dtype="string")
    if group_series.isna().any() or group_series.nunique() < 10:
        raise FeatureValidationError("at least ten complete groups are required")

    features = _validate_training_features(build_pre_lab_features(train))
    if not {"age_years", "sex", "race_ethnicity"}.issubset(features.columns):
        raise FeatureValidationError("age_years, sex, and race_ethnicity are required")
    y = y_series.astype(int).to_numpy()
    split_cv = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=random_state)
    outer_splits = _validated_grouped_splits(
        split_cv, features, y, group_series, context="outer"
    )
    development_index, holdout_index = outer_splits[0]
    development = features.iloc[development_index].reset_index(drop=True)
    holdout = features.iloc[holdout_index].reset_index(drop=True)
    y_development = y[development_index]
    y_holdout = y[holdout_index]
    development_groups = group_series.iloc[development_index].reset_index(drop=True)
    holdout_groups = group_series.iloc[holdout_index].reset_index(drop=True)

    oof_cv = StratifiedGroupKFold(n_splits=4, shuffle=True, random_state=random_state + 1)
    inner_splits = _validated_grouped_splits(
        oof_cv,
        development,
        y_development,
        development_groups,
        context="development",
    )
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
            cv=inner_splits,
            method="predict_proba",
            n_jobs=1,
        )[:, 1]
        fitted[name] = clone(pipeline).fit(development, y_development)

    scorer = _portable_scorer(fitted["logistic_regression"], list(features.columns))
    selection_probabilities = tuple(float(value) for value in oof["logistic_regression"])
    development_decision = select_capacity_decision(selection_probabilities, capacity)
    holdout_probability_map = {
        name: pipeline.predict_proba(holdout)[:, 1] for name, pipeline in fitted.items()
    }
    logistic_holdout = holdout_probability_map["logistic_regression"]
    forest_holdout = holdout_probability_map["random_forest"]
    logistic_decision = select_capacity_decision(logistic_holdout, capacity)
    temporary = ModelComparison(
        models={},
        selected_model="logistic_regression",
        selection_policy="logistic_prespecified_before_holdout",
        selection_probabilities=selection_probabilities,
        holdout_probabilities=tuple(float(value) for value in logistic_holdout),
        selected_threshold=development_decision.threshold,
        threshold_capacity=capacity,
        development_capacity=development_decision,
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
        paired_differences={},
        scorer=scorer,
        features=tuple(features.columns),
        intended_use=(
            "Educational comparison of population-level screening opportunity; "
            "not a diagnosis or clinical decision tool."
        ),
        limitations=(),
    )
    prevalence = float(y_development.mean())
    no_skill_probabilities = np.full(len(y_holdout), prevalence, dtype=float)
    holdout_group_array = holdout_groups.astype(str).to_numpy()
    metrics: dict[str, ModelMetrics] = {
        "prevalence_no_skill": _metrics(
            y_holdout,
            no_skill_probabilities,
            holdout_group_array,
            capacity,
            replicates=bootstrap_replicates,
            random_state=random_state + 10,
        ),
        "logistic_regression": _metrics(
            y_holdout,
            logistic_holdout,
            holdout_group_array,
            capacity,
            replicates=bootstrap_replicates,
            random_state=random_state + 20,
        ),
        "random_forest": _metrics(
            y_holdout,
            forest_holdout,
            holdout_group_array,
            capacity,
            replicates=bootstrap_replicates,
            random_state=random_state + 30,
        ),
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
            if values.isna().any():
                raise FeatureValidationError(
                    "cohort sensitivity must use the common complete-case domain"
                )
            if not set(values.unique()).issubset({0, 1}):
                raise FeatureValidationError("sensitivity outcomes must be binary")
            alternative_y = values.astype(int).to_numpy()
            if len(np.unique(alternative_y)) == 2:
                sensitivity[alternative] = {
                    "holdout_n": int(len(alternative_y)),
                    "holdout_prevalence": float(alternative_y.mean()),
                    "roc_auc": float(roc_auc_score(alternative_y, logistic_holdout)),
                    "pr_auc": float(
                        average_precision_score(alternative_y, logistic_holdout)
                    ),
                }

    return ModelComparison(
        models=metrics,
        selected_model="logistic_regression",
        selection_policy=temporary.selection_policy,
        selection_probabilities=temporary.selection_probabilities,
        holdout_probabilities=temporary.holdout_probabilities,
        selected_threshold=temporary.selected_threshold,
        threshold_capacity=capacity,
        development_capacity=temporary.development_capacity,
        holdout_prevalence=float(y_holdout.mean()),
        holdout_n=int(len(y_holdout)),
        split=temporary.split,
        subgroups=_subgroups(
            holdout,
            y_holdout,
            logistic_holdout,
            np.asarray(logistic_decision.selected, dtype=bool),
            holdout_group_array,
            capacity,
            replicates=bootstrap_replicates,
            random_state=random_state + 40,
        ),
        cohort_sensitivity=sensitivity,
        paired_differences=_paired_metric_differences(
            y_holdout,
            logistic_holdout,
            forest_holdout,
            holdout_group_array,
            replicates=bootstrap_replicates,
            random_state=random_state + 50,
        ),
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
