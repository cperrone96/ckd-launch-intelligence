from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pandas as pd
import pytest

from ckd_intelligence.cohorts import nhanes_2017_2018 as nhanes
from ckd_intelligence.modeling.patient_finding import PRE_LAB_FEATURES


def test_smoking_status_keeps_unknowns_missing() -> None:
    ever = pd.Series([2.0, 1.0, 1.0, 1.0, 1.0, 7.0, None])
    now = pd.Series([None, 1.0, 2.0, 3.0, 9.0, None, None])

    status = nhanes._smoking_status(ever, now)

    assert status.iloc[:4].tolist() == ["Never", "Current", "Current", "Former"]
    assert status.iloc[4:].isna().all()


def test_eligible_domain_excludes_children_and_known_pregnancy_only() -> None:
    people = pd.DataFrame(
        {
            "age_years": [17, 18, 30, 30, 30, None],
            "pregnancy_status_code": [None, None, 1, 2, 3, None],
        }
    )

    assert nhanes.eligible_domain(people).tolist() == [False, True, False, True, True, False]


def test_survey_cluster_labels_combine_stratum_and_psu() -> None:
    people = pd.DataFrame({"strata": [134.0, 134.0, 135.0], "psu": [1.0, 2.0, 1.0]})

    assert nhanes.survey_cluster_labels(people).tolist() == [
        "134-psu-1",
        "134-psu-2",
        "135-psu-1",
    ]


def test_snapshot_absent_falls_back_but_mismatched_bytes_fail_closed(tmp_path: Path) -> None:
    raw = tmp_path / nhanes.RAW_DIRECTORY
    raw.mkdir(parents=True)
    payload = b"verified bytes"
    manifest = {
        "files": [
            {"name": "DEMO_J.xpt", "sha256": sha256(payload).hexdigest(), "bytes": len(payload)}
        ]
    }

    assert nhanes.snapshot_is_available(tmp_path, manifest) is False
    (raw / "DEMO_J.xpt").write_bytes(payload)
    assert nhanes.snapshot_is_available(tmp_path, manifest) is True
    (raw / "DEMO_J.xpt").write_bytes(b"tampered bytes")
    with pytest.raises(nhanes.SnapshotError, match="checksum mismatch"):
        nhanes.snapshot_is_available(tmp_path, manifest)


def test_manifest_lists_every_component_the_loader_reads() -> None:
    manifest = json.loads(Path(nhanes.MANIFEST_PATH).read_text(encoding="utf-8"))

    assert {item["name"] for item in manifest["files"]} == set(nhanes.COMPONENT_COLUMNS)
    assert all(item["url"].startswith("https://wwwn.cdc.gov/") for item in manifest["files"])


_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(
    not (_ROOT / nhanes.RAW_DIRECTORY / "SMQ_J.xpt").is_file(),
    reason="raw NHANES snapshot not downloaded (run scripts/retrieve_surveys.py)",
)
def test_verified_snapshot_reproduces_documented_counts_and_features() -> None:
    manifest = nhanes.load_manifest(_ROOT)
    assert nhanes.snapshot_is_available(_ROOT, manifest)

    frame = nhanes.load_examined_participants(_ROOT)
    people = nhanes.add_ckd_indicators(frame.people)
    domain = nhanes.eligible_domain(people) & people["primary_egfr_or_albuminuria"].notna()

    assert frame.source_participant_count == 9254
    assert len(people) == 8704
    assert int(domain.sum()) == 5016
    assert set(PRE_LAB_FEATURES) <= set(people.columns)
    assert int(people.loc[domain].dropna(subset=list(PRE_LAB_FEATURES)).shape[0]) == 4741
