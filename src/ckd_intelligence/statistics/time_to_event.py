"""Small, dependency-light survival-analysis primitives for portfolio examples.

The implementation is intentionally explicit rather than hiding the risk-set
calculation behind a third-party estimator.  It is suitable for the synthetic
CMS demonstration only; it is not a clinical or Medicare estimator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd
from scipy.stats import norm


@dataclass(frozen=True, slots=True)
class KaplanMeierResult:
    """A deterministic Kaplan--Meier step table.

    ``event_observed`` is true for a target event and false for a right-censoring
    observation.  All arrays use the unique observed event/censoring times in
    ascending order.  Confidence limits use Greenwood's variance with a normal
    approximation and are clipped to [0, 1].
    """

    table: pd.DataFrame
    median_survival: float | None
    confidence_level: float

    @property
    def survival(self) -> np.ndarray:
        return self.table["survival"].to_numpy(dtype=float)


def _array(values: Sequence[float] | np.ndarray, name: str) -> np.ndarray:
    result = np.asarray(values)
    if result.ndim != 1 or result.size == 0:
        raise ValueError(f"{name} must be a non-empty one-dimensional sequence")
    return result


def kaplan_meier(
    durations: Sequence[float] | np.ndarray,
    event_observed: Sequence[bool] | np.ndarray,
    *,
    confidence_level: float = 0.95,
) -> KaplanMeierResult:
    """Compute a Kaplan--Meier estimate with explicit risk sets.

    Durations are measured in the caller's units (the journey example uses days).
    Events and censorings at the same time are counted before moving to the next
    time.  The risk set therefore includes observations whose duration equals the
    current time, which is the standard right-continuous convention.
    """

    time = _array(durations, "durations").astype(float)
    observed = _array(event_observed, "event_observed")
    if len(time) != len(observed):
        raise ValueError("durations and event_observed must have matching lengths")
    if not np.all(np.isfinite(time)) or np.any(time < 0):
        raise ValueError("durations must be finite and non-negative")
    if not all(isinstance(value, (bool, np.bool_)) for value in observed.tolist()):
        raise ValueError("event_observed must contain only booleans")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be between zero and one")

    observed = observed.astype(bool)
    z = float(norm.ppf(0.5 + confidence_level / 2))
    rows: list[dict[str, float | int]] = []
    survival = 1.0
    greenwood_sum = 0.0
    for event_time in np.unique(time):
        at_risk = int(np.sum(time >= event_time))
        events = int(np.sum((time == event_time) & observed))
        censored = int(np.sum((time == event_time) & ~observed))
        if at_risk <= 0 or events > at_risk:
            raise ValueError("invalid risk-set calculation")
        if events:
            survival *= 1.0 - events / at_risk
            if at_risk > events:
                greenwood_sum += events / (at_risk * (at_risk - events))
        standard_error = float(np.sqrt(max(survival * survival * greenwood_sum, 0.0)))
        rows.append(
            {
                "time": float(event_time),
                "at_risk": at_risk,
                "events": events,
                "censored": censored,
                "survival": float(survival),
                "greenwood_variance": float(survival * survival * greenwood_sum),
                "ci_low": max(0.0, float(survival - z * standard_error)),
                "ci_high": min(1.0, float(survival + z * standard_error)),
            }
        )
    table = pd.DataFrame(rows)
    median_rows = table.loc[table["survival"] <= 0.5, "time"]
    median = float(median_rows.iloc[0]) if not median_rows.empty else None
    return KaplanMeierResult(table=table, median_survival=median, confidence_level=confidence_level)


def kaplan_meier_table(
    durations: Sequence[float] | np.ndarray,
    event_observed: Sequence[bool] | np.ndarray,
    *,
    confidence_level: float = 0.95,
) -> pd.DataFrame:
    """Convenience wrapper returning the survival step table."""

    return kaplan_meier(
        durations, event_observed, confidence_level=confidence_level
    ).table.copy()
