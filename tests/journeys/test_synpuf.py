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

