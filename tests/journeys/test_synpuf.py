from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ckd_intelligence.journeys.synpuf import (
    JourneyRules,
    build_journey_output,
    build_synthetic_journeys,
    validate_journey_order,
)
from ckd_intelligence.statistics.time_to_event import kaplan_meier

FIXTURE = Path(__file__).parents[2] / "data" / "fixtures" / "synpuf_journeys.csv"


@pytest.fixture()
def claims() -> pd.DataFrame:
    return pd.read_csv(FIXTURE)


def test_journey_events_are_chronological(claims: pd.DataFrame) -> None:
    journeys = build_synthetic_journeys(claims)
    validate_journey_order(journeys)
    assert journeys.index.equals(
        journeys.sort_values(
            ["synthetic_id", "event_date", "event_through_date", "claim_id"],
            kind="mergesort",
        ).index
    )


def test_journey_is_synthetic_only_and_no_observed_values_are_allowed(
    claims: pd.DataFrame,
) -> None:
    output = build_journey_output(claims)
    assert set(output.events["evidence_type"]) == {"public_synthetic"}
    assert set(output.summaries["evidence_type"]) == {"public_synthetic"}
    with pytest.raises(ValueError, match="public_synthetic"):
        build_journey_output(claims.assign(evidence_type="public_observed"))
    with pytest.raises(ValueError, match="evidence_type"):
        build_journey_output(claims.drop(columns="evidence_type"))
    null_labels = pd.Series(pd.NA, index=claims.index, dtype="object")
    with pytest.raises(ValueError, match="public_synthetic"):
        build_journey_output(claims.assign(evidence_type=null_labels))


def test_schema_valid_empty_input_returns_typed_empty_outputs(
    claims: pd.DataFrame,
) -> None:
    output = build_journey_output(claims.iloc[0:0].copy())
    assert output.events.empty
    assert output.summaries.empty
    assert output.survival.empty
    assert "evidence_type" in output.events


def test_persistence_gap_is_inclusive_and_no_target_is_retained_as_censored(
    claims: pd.DataFrame,
) -> None:
    output = build_journey_output(claims, rules=JourneyRules(persistence_gap_days=90))
    summaries = output.summaries.set_index("synthetic_id")
    assert bool(summaries.loc["SYN001", "event_observed"])
    assert summaries.loc["SYN001", "persistence_date"] == pd.Timestamp("2009-04-10").date()
    assert not bool(summaries.loc["SYN002", "event_observed"])
    assert bool(summaries.loc["SYN002", "has_target"])
    assert not bool(summaries.loc["SYN003", "event_observed"])
    assert bool(summaries.loc["SYN003", "has_target"])


def test_deterministic_tie_break_uses_claim_id(claims: pd.DataFrame) -> None:
    tied = pd.concat(
        [
            claims,
            pd.DataFrame(
                [
                    {
                        "source_release": "2008-2010",
                        "beneficiary_id": "SYN004",
                        "claim_id": "A",
                        "claim_type": "outpatient",
                        "service_from_date": "2009-01-01",
                        "service_through_date": "2009-01-01",
                        "diagnosis_code": "4019",
                        "provider_id": "P400",
                        "payment_amount_usd": 1,
                        "year": 2009,
                        "evidence_type": "public_synthetic",
                    },
                    {
                        "source_release": "2008-2010",
                        "beneficiary_id": "SYN004",
                        "claim_id": "B",
                        "claim_type": "outpatient",
                        "service_from_date": "2009-01-01",
                        "service_through_date": "2009-01-01",
                        "diagnosis_code": "5853",
                        "provider_id": "P400",
                        "payment_amount_usd": 1,
                        "year": 2009,
                        "evidence_type": "public_synthetic",
                    },
                ]
            ),
        ],
        ignore_index=True,
    )
    rows = build_synthetic_journeys(tied)
    assert list(rows.loc[rows["synthetic_id"] == "SYN004", "claim_id"]) == ["A", "B"]


def test_only_first_qualifying_persistence_claim_is_flagged() -> None:
    rows = pd.DataFrame(
        [
            {
                "source_release": "2008-2010",
                "beneficiary_id": "TIE",
                "claim_id": claim_id,
                "claim_type": "outpatient",
                "service_from_date": event_date,
                "service_through_date": event_date,
                "diagnosis_code": diagnosis,
                "evidence_type": "public_synthetic",
            }
            for claim_id, event_date, diagnosis in (
                ("A", "2009-01-01", "4019"),
                ("B", "2009-02-01", "5853"),
                ("D", "2009-05-02", "5853"),
                ("E", "2009-05-02", "4019"),
                ("F", "2009-05-02", "5853"),
            )
        ]
    )
    output = build_journey_output(rows)
    assert list(output.events.loc[output.events["is_persistence_event"], "claim_id"]) == ["D"]
    assert list(output.events["event_order"]) == [0, 2, 3, 3, 3]


def test_post_follow_up_claims_never_define_target_or_persistence(
    claims: pd.DataFrame,
) -> None:
    post_follow_up = pd.DataFrame(
        [
            {
                "source_release": "2008-2010",
                "beneficiary_id": "SYN005",
                "claim_id": "L1",
                "claim_type": "outpatient",
                "service_from_date": "2009-01-01",
                "service_through_date": "2009-01-01",
                "diagnosis_code": "4019",
                "evidence_type": "public_synthetic",
            },
            {
                "source_release": "2008-2010",
                "beneficiary_id": "SYN005",
                "claim_id": "L2",
                "claim_type": "outpatient",
                "service_from_date": "2009-02-01",
                "service_through_date": "2009-02-01",
                "diagnosis_code": "5853",
                "evidence_type": "public_synthetic",
            },
        ]
    )
    output = build_journey_output(post_follow_up, rules=JourneyRules(follow_up_days=30))
    assert list(output.events["claim_id"]) == ["L1"]
    summary = output.summaries.iloc[0]
    assert bool(summary["event_observed"]) is False
    assert bool(summary["has_target"]) is False


def test_spanning_early_claim_is_removed_before_recomputing_index() -> None:
    rows = pd.DataFrame(
        [
            {
                "source_release": "2008-2010",
                "beneficiary_id": "SPAN",
                "claim_id": "SPAN-1",
                "claim_type": "inpatient",
                "service_from_date": "2009-01-01",
                "service_through_date": "2010-02-01",
                "diagnosis_code": "4019",
                "evidence_type": "public_synthetic",
            },
            {
                "source_release": "2008-2010",
                "beneficiary_id": "SPAN",
                "claim_id": "SPAN-2",
                "claim_type": "outpatient",
                "service_from_date": "2009-12-01",
                "service_through_date": "2009-12-01",
                "diagnosis_code": "5853",
                "evidence_type": "public_synthetic",
            },
        ]
    )
    output = build_journey_output(rows)
    assert list(output.events["claim_id"]) == ["SPAN-2"]
    assert output.summaries.iloc[0]["index_date"] == pd.Timestamp("2009-12-01").date()


def test_spanning_only_input_returns_typed_empty_outputs() -> None:
    rows = pd.DataFrame(
        [
            {
                "source_release": "2008-2010",
                "beneficiary_id": "SPAN-ONLY",
                "claim_id": "SPAN-ONLY-1",
                "claim_type": "inpatient",
                "service_from_date": "2009-01-01",
                "service_through_date": "2010-02-01",
                "diagnosis_code": "5853",
                "evidence_type": "public_synthetic",
            }
        ]
    )
    output = build_journey_output(rows)
    assert output.events.empty
    assert output.summaries.empty
    assert output.survival.empty
    assert list(output.events.columns) == [
        "synthetic_id",
        "claim_id",
        "source_release",
        "event_date",
        "event_through_date",
        "claim_type",
        "diagnosis_code",
        "event_kind",
        "event_order",
        "is_ckd_signal",
        "is_target_event",
        "is_persistence_event",
        "index_date",
        "target_date",
        "persistence_date",
        "follow_up_end",
        "evidence_type",
    ]
    assert list(output.summaries.columns) == [
        "synthetic_id",
        "index_date",
        "target_date",
        "persistence_date",
        "observation_end",
        "duration_days",
        "event_observed",
        "censoring_reason",
        "has_target",
        "evidence_type",
    ]
    assert list(output.survival.columns) == [
        "time",
        "at_risk",
        "events",
        "censored",
        "survival",
        "greenwood_variance",
        "ci_low",
        "ci_high",
        "evidence_type",
    ]


def test_out_of_release_through_date_is_rejected(claims: pd.DataFrame) -> None:
    invalid = claims.copy()
    invalid.loc[0, "service_through_date"] = "2011-01-01"
    with pytest.raises(ValueError, match="observation window"):
        build_journey_output(invalid)


def test_python_outputs_include_reconciliable_summary_and_survival_tables(
    claims: pd.DataFrame,
) -> None:
    output = build_journey_output(claims)
    assert len(output.events) == len(claims)
    assert len(output.summaries) == claims["beneficiary_id"].nunique()
    assert set(output.survival["evidence_type"]) == {"public_synthetic"}
    assert output.survival[["at_risk", "events", "censored"]].to_dict("records") == [
        {"at_risk": 3, "events": 1, "censored": 0},
        {"at_risk": 2, "events": 0, "censored": 2},
    ]


def test_kaplan_meier_matches_hand_calculation_and_is_monotone() -> None:
    result = kaplan_meier([1, 2, 2, 4], [True, False, True, True])
    assert list(result.table["at_risk"]) == [4, 3, 1]
    assert list(result.table["events"]) == [1, 1, 1]
    assert list(result.table["censored"]) == [0, 1, 0]
    assert list(result.table["survival"].round(8)) == [0.75, 0.5, 0.0]
    assert (result.table["survival"].diff().dropna() <= 0).all()
    assert result.median_survival == 2.0


@pytest.mark.parametrize(
    "durations,events",
    [([], []), ([-1], [True]), ([1, 2], [True])],
)
def test_kaplan_meier_validates_inputs(durations: list[float], events: list[bool]) -> None:
    with pytest.raises(ValueError):
        kaplan_meier(durations, events)
