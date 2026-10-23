from __future__ import annotations

import json
import shutil
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
from journeys.provenance import load_verified_synpuf_fixture

FIXTURE = Path(__file__).parents[2] / "data" / "fixtures" / "synpuf_journeys.csv"


@pytest.fixture()
def claims() -> pd.DataFrame:
    return load_verified_synpuf_fixture()


def test_synpuf_manifest_rejects_changed_bytes_and_metadata(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    fixture_path = tmp_path / "synpuf_journeys.csv"
    shutil.copyfile(FIXTURE, fixture_path)
    manifest = json.loads(
        (FIXTURE.parent.parent / "manifests" / "synpuf-journeys-fixture.json").read_text(
            encoding="utf-8"
        )
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    load_verified_synpuf_fixture(manifest_path, fixture_path)

    fixture_path.write_bytes(fixture_path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="fixture_sha256"):
        load_verified_synpuf_fixture(manifest_path, fixture_path)

    shutil.copyfile(FIXTURE, fixture_path)
    for field, value in (
        ("fixture_path", "data/fixtures/other.csv"),
        ("evidence_type", "public_observed"),
        ("fixture_kind", "official_extract"),
        ("source_rows_are_official", True),
        ("no_cross_source_join", False),
    ):
        changed = dict(manifest)
        changed[field] = value
        manifest_path.write_text(json.dumps(changed), encoding="utf-8")
        with pytest.raises(ValueError, match=field):
            load_verified_synpuf_fixture(manifest_path, fixture_path)


def test_notebook_validates_manifest_before_reading_fixture() -> None:
    notebook = FIXTURE.parents[2] / "notebooks" / "04_synthetic_journeys.ipynb"
    cells = json.loads(notebook.read_text(encoding="utf-8"))["cells"]
    load_cell = next(cell for cell in cells if cell.get("id") == "load-synthetic-fixture")
    source = "".join(load_cell["source"])
    assert source.index("validate_synpuf_fixture_manifest") < source.index("pd.read_csv")
    assert "data' / 'manifests' / 'synpuf-journeys-fixture.json" in source


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


def _rows(*rows: tuple[str, str, str, str, str]) -> pd.DataFrame:
    """Build claims from (beneficiary, claim, from, through, diagnosis) tuples."""

    return pd.DataFrame(
        [
            {
                "source_release": "2008-2010",
                "beneficiary_id": beneficiary_id,
                "claim_id": claim_id,
                "claim_type": "outpatient",
                "service_from_date": from_date,
                "service_through_date": through_date,
                "diagnosis_code": diagnosis,
                "evidence_type": "public_synthetic",
            }
            for beneficiary_id, claim_id, from_date, through_date, diagnosis in rows
        ]
    )


def _day(value: str) -> object:
    return pd.Timestamp(value).date()


def test_persistence_gap_is_inclusive_and_clock_starts_at_target(
    claims: pd.DataFrame,
) -> None:
    output = build_journey_output(claims, rules=JourneyRules(persistence_gap_days=90))
    summaries = output.summaries.set_index("synthetic_id")
    # SYN001: target 2009-01-10, second CKD claim exactly 90 days later.
    assert bool(summaries.loc["SYN001", "event_observed"])
    assert summaries.loc["SYN001", "persistence_date"] == _day("2009-04-10")
    assert summaries.loc["SYN001", "duration_days"] == 90
    # SYN003: nine event-free days before its target do not count as follow-up.
    assert summaries.loc["SYN003", "index_date"] == _day("2009-01-01")
    assert summaries.loc["SYN003", "target_date"] == _day("2009-05-01")
    assert summaries.loc["SYN003", "observation_end"] == _day("2010-04-30")
    for synthetic_id in ("SYN002", "SYN003"):
        assert not bool(summaries.loc[synthetic_id, "event_observed"])
        assert summaries.loc[synthetic_id, "duration_days"] == 364


def test_durations_never_start_before_the_target_date(claims: pd.DataFrame) -> None:
    extra = _rows(
        ("LATE", "LATE-1", "2008-01-01", "2008-01-01", "4019"),
        ("LATE", "LATE-2", "2010-06-01", "2010-06-01", "5853"),
        ("LATE", "LATE-3", "2010-10-01", "2010-10-01", "5853"),
        ("NONE", "NONE-1", "2008-02-01", "2008-02-01", "4019"),
    )
    output = build_journey_output(pd.concat([claims, extra], ignore_index=True))
    summaries = output.summaries
    assert (summaries["target_date"] >= summaries["index_date"]).all()
    assert (summaries["duration_days"] >= 0).all()
    ends = [
        persistence if observed else end
        for persistence, end, observed in zip(
            summaries["persistence_date"],
            summaries["observation_end"],
            summaries["event_observed"],
            strict=True,
        )
    ]
    measured = [
        (end - target).days for end, target in zip(ends, summaries["target_date"], strict=True)
    ]
    assert measured == list(summaries["duration_days"])
    assert (summaries["duration_days"] <= 364).all()
    follow_up = output.events.loc[output.events["event_kind"] == "follow_up"]
    assert (follow_up["event_date"] >= follow_up["target_date"]).all()
    assert (follow_up["event_date"] <= follow_up["follow_up_end"]).all()
    # A target nearly 900 days after the first claim still gets a full clock.
    late = summaries.set_index("synthetic_id").loc["LATE"]
    assert bool(late["event_observed"])
    assert late["duration_days"] == 122


def test_people_without_a_target_are_excluded_from_kaplan_meier(
    claims: pd.DataFrame,
) -> None:
    no_target = _rows(
        ("NONE1", "N1", "2008-02-01", "2008-02-01", "4019"),
        ("NONE2", "N2", "2010-12-30", "2010-12-31", "25000"),
    )
    with_none = build_journey_output(pd.concat([claims, no_target], ignore_index=True))
    baseline = build_journey_output(claims)
    assert with_none.excluded_without_target == ("NONE1", "NONE2")
    assert set(with_none.events["synthetic_id"]) >= {"NONE1", "NONE2"}
    assert with_none.events.loc[
        with_none.events["synthetic_id"].isin(["NONE1", "NONE2"]), "follow_up_end"
    ].isna().all()
    assert "NONE1" not in set(with_none.summaries["synthetic_id"])
    assert with_none.summaries["has_target"].all()
    assert int(with_none.survival["at_risk"].max()) == len(with_none.summaries)
    pd.testing.assert_frame_equal(with_none.survival, baseline.survival)

    only_none = build_journey_output(no_target)
    assert len(only_none.events) == 2
    assert only_none.summaries.empty
    assert only_none.survival.empty
    assert only_none.median_survival is None


def test_follow_up_window_is_365_calendar_days_from_target() -> None:
    rows = _rows(
        # 2008 is a leap year: day 364 after 2008-03-01 is 2009-02-28.
        ("EDGE", "E1", "2008-03-01", "2008-03-01", "5853"),
        ("EDGE", "E2", "2009-02-28", "2009-02-28", "5853"),
        ("EDGE", "E3", "2009-03-01", "2009-03-01", "5853"),
        ("OUT", "O1", "2008-03-01", "2008-03-01", "5853"),
        ("OUT", "O2", "2009-03-01", "2009-03-01", "5853"),
    )
    output = build_journey_output(rows)
    summaries = output.summaries.set_index("synthetic_id")
    assert summaries.loc["EDGE", "observation_end"] == _day("2009-02-28")
    assert summaries.loc["EDGE", "persistence_date"] == _day("2009-02-28")
    assert summaries.loc["EDGE", "duration_days"] == 364
    assert not bool(summaries.loc["OUT", "event_observed"])
    assert summaries.loc["OUT", "duration_days"] == 364
    assert list(output.events["claim_id"]) == ["E1", "E2", "O1"]


def test_follow_up_is_cut_at_the_observation_end() -> None:
    output = build_journey_output(_rows(("END", "X1", "2010-10-01", "2010-10-01", "5853")))
    summary = output.summaries.iloc[0]
    assert summary["observation_end"] == _day("2010-12-31")
    assert summary["duration_days"] == 91


def test_spanning_claims_are_dropped_before_index_without_losing_later_claims() -> None:
    # Regression: an early long claim used to set a cutoff that removed C3 for good.
    rows = _rows(
        ("R", "C1", "2008-01-01", "2009-06-01", "4019"),
        ("R", "C2", "2008-03-01", "2008-03-01", "5853"),
        ("R", "C3", "2009-02-15", "2009-02-15", "5853"),
    )
    output = build_journey_output(rows)
    assert list(output.events["claim_id"]) == ["C2", "C3"]
    summary = output.summaries.iloc[0]
    assert summary["index_date"] == _day("2008-03-01")
    assert summary["persistence_date"] == _day("2009-02-15")
    assert bool(summary["event_observed"])
    assert summary["duration_days"] == 351


def test_spanning_boundary_keeps_a_365_day_claim_and_drops_a_366_day_claim() -> None:
    rows = _rows(
        ("KEEP", "K1", "2009-01-01", "2009-12-31", "5853"),
        ("DROP", "D1", "2009-01-01", "2010-01-01", "5853"),
    )
    output = build_journey_output(rows)
    assert list(output.events["claim_id"]) == ["K1"]


def test_rules_reject_non_positive_windows() -> None:
    with pytest.raises(ValueError, match="positive"):
        JourneyRules(follow_up_days=0)
    with pytest.raises(ValueError, match="positive"):
        JourneyRules(persistence_gap_days=0)


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


def test_post_follow_up_claims_never_define_persistence() -> None:
    rows = _rows(
        ("SYN005", "L1", "2009-01-01", "2009-01-01", "4019"),
        ("SYN005", "L2", "2009-02-01", "2009-02-01", "5853"),
        ("SYN005", "L3", "2009-05-01", "2009-05-01", "5853"),
    )
    output = build_journey_output(rows, rules=JourneyRules(follow_up_days=30))
    assert list(output.events["claim_id"]) == ["L1", "L2"]
    summary = output.summaries.iloc[0]
    assert summary["target_date"] == _day("2009-02-01")
    assert summary["observation_end"] == _day("2009-03-02")
    assert bool(summary["event_observed"]) is False
    assert summary["duration_days"] == 29


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
    assert output.survival[["time", "at_risk", "events", "censored"]].to_dict("records") == [
        {"time": 90.0, "at_risk": 3, "events": 1, "censored": 0},
        {"time": 364.0, "at_risk": 2, "events": 0, "censored": 2},
    ]
    assert list(output.survival["survival"].round(6)) == [0.666667, 0.666667]


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
