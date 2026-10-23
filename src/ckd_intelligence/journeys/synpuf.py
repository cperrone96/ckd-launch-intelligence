"""Chronological CMS DE-SynPUF journey construction.

This module demonstrates claims-engineering and follow-up rules on the CMS
2008--2010 public synthetic sample.  The identifiers and the resulting journeys
are synthetic and must never be presented as estimates for Medicare beneficiaries.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Final, cast

import pandas as pd

from ckd_intelligence.statistics.time_to_event import kaplan_meier

EvidenceType: Final[str] = "public_synthetic"
SYNPUF_FIXTURE_RELATIVE_PATH: Final[str] = "data/fixtures/synpuf_journeys.csv"
CKD_ICD9_PREFIXES: Final[tuple[str, ...]] = ("585", "586", "588")
REQUIRED_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "source_release",
        "beneficiary_id",
        "claim_id",
        "claim_type",
        "service_from_date",
        "service_through_date",
        "diagnosis_code",
    }
)


def validate_synpuf_fixture_manifest(
    manifest_path: Path, fixture_path: Path
) -> dict[str, Any]:
    """Validate the synthetic fixture boundary before any CSV bytes are read."""

    try:
        manifest = cast(
            dict[str, Any], json.loads(manifest_path.read_text(encoding="utf-8"))
        )
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("SynPUF fixture manifest is unreadable") from error
    if manifest.get("fixture_path") != SYNPUF_FIXTURE_RELATIVE_PATH:
        raise ValueError("SynPUF fixture manifest fixture_path is invalid")
    if manifest.get("evidence_type") != EvidenceType:
        raise ValueError("SynPUF fixture manifest evidence_type must be public_synthetic")
    if manifest.get("fixture_kind") != "fixture_only":
        raise ValueError("SynPUF fixture manifest fixture_kind must be fixture_only")
    if manifest.get("source_rows_are_official") is not False:
        raise ValueError("SynPUF fixture manifest source_rows_are_official must be false")
    if manifest.get("no_cross_source_join") is not True:
        raise ValueError("SynPUF fixture manifest no_cross_source_join must be true")
    if not isinstance(manifest.get("limitations"), str) or not manifest["limitations"].strip():
        raise ValueError("SynPUF fixture manifest limitations must be non-empty")
    try:
        fixture_bytes = fixture_path.read_bytes()
    except OSError as error:
        raise ValueError("SynPUF fixture is unreadable") from error
    digest = hashlib.sha256(fixture_bytes).hexdigest()
    if manifest.get("fixture_sha256") != digest:
        raise ValueError("SynPUF fixture manifest fixture_sha256 is stale")
    return manifest


@dataclass(frozen=True, slots=True)
class JourneyRules:
    """Versioned journey definitions used by the demonstration."""

    observation_start: date = date(2008, 1, 1)
    observation_end: date = date(2010, 12, 31)
    follow_up_days: int = 365
    persistence_gap_days: int = 90
    target_prefixes: tuple[str, ...] = CKD_ICD9_PREFIXES
    allowed_event_order: tuple[str, ...] = (
        "index",
        "pre_target",
        "target",
        "follow_up",
    )

    def __post_init__(self) -> None:
        if self.observation_end < self.observation_start:
            raise ValueError("observation_end must not precede observation_start")
        if self.follow_up_days < 1 or self.persistence_gap_days < 1:
            raise ValueError("follow_up_days and persistence_gap_days must be positive")

    @property
    def rule_text(self) -> str:
        return (
            "Claims whose service range covers more than "
            f"{self.follow_up_days} calendar days are dropped first. Events are sorted "
            "by event date, through date, and claim ID. The index date is the first "
            "remaining claim date per synthetic beneficiary. The target is the first "
            "diagnosis code beginning with one of the CKD ICD-9 prefixes "
            f"{self.target_prefixes}, and the target date is the time origin. Follow-up "
            f"covers {self.follow_up_days} calendar days, day 0 (the target date) "
            f"through day {self.follow_up_days - 1}, and is cut at the global "
            "observation end if that comes first. A target is persistent when another "
            f"CKD claim starts at least {self.persistence_gap_days} days after the "
            "target date (the boundary is inclusive) and within follow-up. Duration is "
            "days from the target date to persistence or to the follow-up end "
            "(right-censored). Claims after the follow-up end are dropped. People "
            "without a target code have no time origin and are excluded from the "
            "summaries and the Kaplan-Meier table."
        )


@dataclass(frozen=True, slots=True)
class JourneyOutput:
    """Event and beneficiary-level outputs from the deterministic rules."""

    events: pd.DataFrame
    summaries: pd.DataFrame
    survival: pd.DataFrame
    rules: JourneyRules = field(default_factory=JourneyRules)

    @property
    def median_survival(self) -> float | None:
        """Return the first KM time at or below 0.5, if one exists."""

        eligible = self.survival.loc[self.survival["survival"] <= 0.5, "time"]
        return float(eligible.iloc[0]) if not eligible.empty else None

    @property
    def excluded_without_target(self) -> tuple[str, ...]:
        """Synthetic IDs with eligible claims but no target code (not in KM)."""

        no_target = self.events.loc[self.events["target_date"].isna(), "synthetic_id"]
        return tuple(sorted(str(value) for value in no_target.unique()))


def _is_ckd_code(value: object, prefixes: tuple[str, ...]) -> bool:
    code = "" if value is None else str(value).strip().upper().replace(".", "")
    return bool(code) and any(code.startswith(prefix.replace(".", "")) for prefix in prefixes)


def _as_date(value: object, field_name: str) -> date:
    parsed: Any = pd.to_datetime(str(value), errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"{field_name} contains an invalid date")
    return cast(date, parsed.date())


def _validate_input(claims: pd.DataFrame, rules: JourneyRules) -> pd.DataFrame:
    missing = REQUIRED_COLUMNS.difference(claims.columns)
    if missing:
        raise ValueError(f"claims missing required columns: {sorted(missing)}")
    frame = claims.copy()
    if "evidence_type" not in frame:
        raise ValueError("journey input must include an evidence_type column")
    if frame["evidence_type"].isna().any() or (
        not frame.empty and set(frame["evidence_type"].astype(str)) != {EvidenceType}
    ):
        raise ValueError("journey input must contain evidence_type=public_synthetic only")
    if frame["source_release"].isna().any() or (
        not frame.empty and set(frame["source_release"].astype(str)) != {"2008-2010"}
    ):
        raise ValueError("journey input must contain source_release=2008-2010 only")
    if frame["beneficiary_id"].isna().any() or frame["claim_id"].isna().any():
        raise ValueError("beneficiary_id and claim_id must not be missing")
    if frame["claim_type"].isna().any():
        raise ValueError("claim_type must not be missing")
    if frame["claim_id"].duplicated().any():
        raise ValueError("claim_id must be unique in the journey input")
    frame["beneficiary_id"] = frame["beneficiary_id"].astype(str)
    frame["claim_id"] = frame["claim_id"].astype(str)
    frame["event_date"] = frame["service_from_date"].map(
        lambda value: _as_date(value, "service_from_date")
    )
    frame["event_through_date"] = frame["service_through_date"].map(
        lambda value: _as_date(value, "service_through_date")
    )
    if (frame["event_through_date"] < frame["event_date"]).any():
        raise ValueError("service_through_date must not precede service_from_date")
    if (
        (frame["event_date"] < rules.observation_start)
        | (frame["event_date"] > rules.observation_end)
        | (frame["event_through_date"] < rules.observation_start)
        | (frame["event_through_date"] > rules.observation_end)
    ).any():
        raise ValueError("service dates must be within the 2008-2010 observation window")
    return frame


def _empty_events() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "synthetic_id": pd.Series(dtype="string"),
            "claim_id": pd.Series(dtype="string"),
            "source_release": pd.Series(dtype="string"),
            "event_date": pd.Series(dtype="object"),
            "event_through_date": pd.Series(dtype="object"),
            "claim_type": pd.Series(dtype="string"),
            "diagnosis_code": pd.Series(dtype="string"),
            "event_kind": pd.Series(dtype="string"),
            "event_order": pd.Series(dtype="int64"),
            "is_ckd_signal": pd.Series(dtype="bool"),
            "is_target_event": pd.Series(dtype="bool"),
            "is_persistence_event": pd.Series(dtype="bool"),
            "index_date": pd.Series(dtype="object"),
            "target_date": pd.Series(dtype="object"),
            "persistence_date": pd.Series(dtype="object"),
            "follow_up_end": pd.Series(dtype="object"),
            "evidence_type": pd.Series(dtype="string"),
        }
    )


def _empty_summaries() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "synthetic_id": pd.Series(dtype="string"),
            "index_date": pd.Series(dtype="object"),
            "target_date": pd.Series(dtype="object"),
            "persistence_date": pd.Series(dtype="object"),
            "observation_end": pd.Series(dtype="object"),
            "duration_days": pd.Series(dtype="int64"),
            "event_observed": pd.Series(dtype="bool"),
            "censoring_reason": pd.Series(dtype="string"),
            "has_target": pd.Series(dtype="bool"),
            "evidence_type": pd.Series(dtype="string"),
        }
    )


def _empty_survival() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": pd.Series(dtype="float64"),
            "at_risk": pd.Series(dtype="int64"),
            "events": pd.Series(dtype="int64"),
            "censored": pd.Series(dtype="int64"),
            "survival": pd.Series(dtype="float64"),
            "greenwood_variance": pd.Series(dtype="float64"),
            "ci_low": pd.Series(dtype="float64"),
            "ci_high": pd.Series(dtype="float64"),
            "evidence_type": pd.Series(dtype="string"),
        }
    )


def build_journey_output(
    claims: pd.DataFrame,
    *,
    rules: JourneyRules | None = None,
) -> JourneyOutput:
    """Build event, summary, and survival tables from normalized synthetic claims.

    Claims whose service range covers more than ``follow_up_days`` calendar days
    are dropped before anything else, so the index and target dates are computed
    once from the remaining claims.  The persistence clock starts at the target
    date; people without a target code appear in the event table only.  The
    function does not mutate its input and never performs a cross-source join.
    """

    journey_rules = rules or JourneyRules()
    if set(journey_rules.allowed_event_order) != {
        "index",
        "pre_target",
        "target",
        "follow_up",
    } or len(journey_rules.allowed_event_order) != 4:
        raise ValueError("allowed_event_order must contain each documented event kind exactly once")
    event_order = {
        kind: position for position, kind in enumerate(journey_rules.allowed_event_order)
    }
    frame: Any = _validate_input(claims, journey_rules)
    # Drop spanning claims up front, exactly like the SQL mart, so a removed
    # claim can never move the index date or hide a later valid claim.
    span_days = [
        (through - start).days
        for start, through in zip(frame["event_date"], frame["event_through_date"], strict=True)
    ]
    frame = frame.loc[[days < journey_rules.follow_up_days for days in span_days]]
    frame = frame.sort_values(
        ["beneficiary_id", "event_date", "event_through_date", "claim_id"],
        kind="mergesort",
    ).reset_index(drop=True)
    if frame.empty:
        return JourneyOutput(_empty_events(), _empty_summaries(), _empty_survival(), journey_rules)

    last_follow_up_day = timedelta(days=journey_rules.follow_up_days - 1)
    persistence_gap = timedelta(days=journey_rules.persistence_gap_days)
    event_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for synthetic_id, group in frame.groupby("beneficiary_id", sort=False):
        group = group.reset_index(drop=True)
        index_date = group.loc[0, "event_date"]
        is_target = group["diagnosis_code"].map(
            lambda value: _is_ckd_code(value, journey_rules.target_prefixes)
        )
        target_positions = [int(position) for position in group.index[is_target]]
        target_position = target_positions[0] if target_positions else None
        target_date = (
            group.loc[target_position, "event_date"] if target_position is not None else None
        )
        follow_up_end = (
            min(journey_rules.observation_end, target_date + last_follow_up_day)
            if target_date is not None
            else None
        )
        if follow_up_end is not None:
            # Rows are sorted by event date, so this keeps a prefix and the
            # target position is unchanged.
            group = group.loc[group["event_date"] <= follow_up_end]
            is_target = is_target.loc[group.index]
            target_positions = [
                position for position in target_positions if position in group.index
            ]
        persistence_position: int | None = None
        if target_date is not None:
            for position in target_positions[1:]:
                if group.loc[position, "event_date"] >= target_date + persistence_gap:
                    persistence_position = position
                    break
        persistence_date = (
            group.loc[persistence_position, "event_date"]
            if persistence_position is not None
            else None
        )
        for position, row in group.iterrows():
            if position == 0:
                event_kind = "index"
            elif position == target_position:
                event_kind = "target"
            elif target_position is None or position < target_position:
                event_kind = "pre_target"
            else:
                event_kind = "follow_up"
            event_rows.append(
                {
                    "synthetic_id": str(synthetic_id),
                    "claim_id": str(row["claim_id"]),
                    "source_release": "2008-2010",
                    "event_date": row["event_date"],
                    "event_through_date": row["event_through_date"],
                    "claim_type": str(row["claim_type"]),
                    "diagnosis_code": str(row["diagnosis_code"]),
                    "event_kind": event_kind,
                    "event_order": event_order[event_kind],
                    "is_ckd_signal": bool(is_target.loc[position]),
                    "is_target_event": target_position == position,
                    "is_persistence_event": persistence_position == position,
                    "index_date": index_date,
                    "target_date": target_date,
                    "persistence_date": persistence_date,
                    "follow_up_end": follow_up_end,
                    "evidence_type": EvidenceType,
                }
            )
        if target_date is None or follow_up_end is None:
            # No target code means no time origin: the person is shown in the
            # event table but is not part of the persistence risk set.
            continue
        event_observed = persistence_date is not None
        end_date = persistence_date if persistence_date is not None else follow_up_end
        summaries.append(
            {
                "synthetic_id": str(synthetic_id),
                "index_date": index_date,
                "target_date": target_date,
                "persistence_date": persistence_date,
                "observation_end": follow_up_end,
                "duration_days": int((end_date - target_date).days),
                "event_observed": event_observed,
                "censoring_reason": None if event_observed else "right_censored_at_follow_up_end",
                "has_target": True,
                "evidence_type": EvidenceType,
            }
        )
    events = pd.DataFrame(event_rows).sort_values(
        ["synthetic_id", "event_date", "event_through_date", "claim_id"],
        kind="mergesort",
    ).reset_index(drop=True)
    if not summaries:
        return JourneyOutput(events, _empty_summaries(), _empty_survival(), journey_rules)
    summary_frame = pd.DataFrame(summaries).sort_values("synthetic_id").reset_index(drop=True)
    km = kaplan_meier(
        summary_frame["duration_days"].to_numpy(dtype=float),
        summary_frame["event_observed"].to_numpy(dtype=bool),
    ).table
    km.insert(0, "evidence_type", EvidenceType)
    return JourneyOutput(
        events=events,
        summaries=summary_frame,
        survival=km,
        rules=journey_rules,
    )


def build_synthetic_journeys(
    claims: pd.DataFrame, *, rules: JourneyRules | None = None
) -> pd.DataFrame:
    """Return the chronological synthetic event table."""

    return build_journey_output(claims, rules=rules).events


def summarize_synthetic_journeys(
    claims: pd.DataFrame, *, rules: JourneyRules | None = None
) -> pd.DataFrame:
    """Return one persistence observation per synthetic beneficiary with a target code."""

    return build_journey_output(claims, rules=rules).summaries


def validate_journey_order(journeys: pd.DataFrame) -> None:
    """Raise when event rows are not in their documented deterministic order."""

    required = {"synthetic_id", "event_date", "event_through_date", "claim_id"}
    if not required.issubset(journeys.columns):
        missing = sorted(required.difference(journeys.columns))
        raise ValueError(f"journeys missing columns: {missing}")
    expected = journeys.sort_values(
        ["synthetic_id", "event_date", "event_through_date", "claim_id"],
        kind="mergesort",
    ).index
    if not expected.equals(journeys.index):
        raise ValueError("journey events are not chronological with deterministic tie-breaks")
