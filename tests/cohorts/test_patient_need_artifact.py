from __future__ import annotations

import json
from pathlib import Path

import pytest

from ckd_intelligence.analysis.artifacts import patient_need_output_paths


def test_fixture_output_cannot_overwrite_official_patient_need_artifact() -> None:
    official, official_checksum = patient_need_output_paths(Path("data"), "public_observed")
    fixture, fixture_checksum = patient_need_output_paths(Path("data"), "fixture_only")

    assert official == Path("data/processed/patient_need_summary.json")
    assert official_checksum == Path("data/processed/patient_need_summary.sha256")
    assert fixture == Path("data/processed/fixture/patient_need_summary_fixture.json")
    assert fixture_checksum == Path("data/processed/fixture/patient_need_summary_fixture.sha256")
    assert fixture != official


def test_official_aggregate_artifact_reconciles_to_reviewed_nhanes_snapshot() -> None:
    artifact = json.loads(
        Path("data/processed/patient_need_summary.json").read_text(encoding="utf-8")
    )

    assert artifact["evidence_type"] == "public_observed"
    assert [(stage["stage"], stage["people"]) for stage in artifact["waterfall"]] == [
        ("NHANES 2017-2018 participants", 9254),
        ("MEC examined with valid design and positive weight", 8704),
        ("adults age 18+", 5533),
        ("adults excluding known pregnancy", 5478),
        ("complete eGFR and UACR defining labs", 5016),
        ("cross-sectional CKD indicator positive", 938),
    ]
    estimates = artifact["estimates"]
    assert {estimate["denominator"] for estimate in estimates.values()} == {5016}
    assert {estimate["excluded_missing"] for estimate in estimates.values()} == {462}
    assert estimates["primary_egfr_or_albuminuria"]["point"] == pytest.approx(0.139189, abs=1e-6)
