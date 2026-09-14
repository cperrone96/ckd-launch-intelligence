from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest

ROOT = Path(__file__).parents[2]


def _assert_verified_artifact_files(
    artifact_path: Path,
    checksum_path: Path,
    manifest_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Require an exact three-way artifact/checksum/manifest contract."""

    assert artifact_path.exists(), artifact_path
    assert checksum_path.exists(), checksum_path
    assert manifest_path.exists(), manifest_path
    artifact_digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    checksum_text = checksum_path.read_text(encoding="utf-8")
    checksum_lines = checksum_text.splitlines()
    assert len(checksum_lines) == 1, "checksum sidecar must contain exactly one line"
    checksum_fields = checksum_lines[0].split("  ")
    assert len(checksum_fields) == 2, "checksum sidecar must contain digest and filename"
    sidecar_digest, sidecar_filename = checksum_fields
    assert sidecar_digest == artifact_digest, "checksum sidecar digest is stale"
    assert sidecar_filename == artifact_path.name, "checksum sidecar filename is wrong"
    assert checksum_text == f"{artifact_digest}  {artifact_path.name}\n", (
        "checksum sidecar has non-canonical content"
    )
    artifact = cast(dict[str, Any], json.loads(artifact_path.read_text(encoding="utf-8")))
    manifest = cast(dict[str, Any], json.loads(manifest_path.read_text(encoding="utf-8")))
    try:
        expected_path = artifact_path.relative_to(ROOT).as_posix()
    except ValueError:
        expected_path = artifact_path.name
    assert manifest["artifact_path"] == expected_path
    assert manifest["artifact_sha256"] == artifact_digest, "manifest artifact_sha256 is stale"
    return artifact, manifest


def _verified_artifact(stem: str) -> tuple[dict[str, Any], dict[str, Any]]:
    artifact_path = ROOT / "data" / "processed" / f"{stem}.json"
    checksum_path = ROOT / "data" / "processed" / f"{stem}.sha256"
    manifest_path = ROOT / "data" / "manifests" / f"{stem}.json"
    return _assert_verified_artifact_files(artifact_path, checksum_path, manifest_path)


def test_artifact_checksum_contract_rejects_changed_bytes_and_metadata(tmp_path: Path) -> None:
    artifact_path = tmp_path / "artifact.json"
    checksum_path = tmp_path / "artifact.sha256"
    manifest_path = tmp_path / "manifest.json"
    artifact_path.write_text('{"value": 1}\n', encoding="utf-8")
    digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    checksum_path.write_text(f"{digest}  artifact.json\n", encoding="utf-8")
    manifest_path.write_text(
        json.dumps({"artifact_path": "artifact.json", "artifact_sha256": digest}),
        encoding="utf-8",
    )
    _assert_verified_artifact_files(artifact_path, checksum_path, manifest_path)

    artifact_path.write_text('{"value": 2}\n', encoding="utf-8")
    with pytest.raises(AssertionError, match="stale"):
        _assert_verified_artifact_files(artifact_path, checksum_path, manifest_path)

    artifact_path.write_text('{"value": 1}\n', encoding="utf-8")
    checksum_path.write_text(f"{digest}  wrong.json\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="filename"):
        _assert_verified_artifact_files(artifact_path, checksum_path, manifest_path)

    checksum_path.write_text(f"{digest}  artifact.json\nextra\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="exactly one line"):
        _assert_verified_artifact_files(artifact_path, checksum_path, manifest_path)

    checksum_path.write_text(f"{digest}  artifact.json\n", encoding="utf-8")
    manifest_path.write_text(
        json.dumps({"artifact_path": "artifact.json", "artifact_sha256": "stale"}),
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="artifact_sha256"):
        _assert_verified_artifact_files(artifact_path, checksum_path, manifest_path)


def test_meps_public_artifact_is_hc243_2022_and_not_event_person_ambiguous() -> None:
    artifact, manifest = _verified_artifact("meps_hc243_2022_landscape")
    assert artifact["evidence_type"] == "public_observed"
    assert artifact["release"] == "HC-243-2022"
    assert artifact["retrieved_at"] == manifest["retrieved_at"]
    assert artifact["definition"]["proxy_variable"] == "DSKIDN53"
    assert artifact["definition"]["proxy_is_not_confirmed_ckd"] is True
    assert artifact["denominators"]["all_person_records"] == 22431
    assert artifact["estimates"]
    assert all("person_id" not in json.dumps(row).lower() for row in artifact["estimates"])


def test_partd_artifact_proves_pages_and_suppression_limit() -> None:
    artifact, manifest = _verified_artifact("partd_2024_ckd_therapy_landscape")
    assert artifact["evidence_type"] == "public_observed"
    assert artifact["release"] == "2024"
    assert artifact["dictionary_version"] == "ckd-therapy-dictionary-v1"
    assert artifact["pagination"]["complete_for_selected_generics"] is True
    assert artifact["pagination"]["rows_retrieved"] == sum(
        item["rows_retrieved"] for item in artifact["pagination"]["generic_pages"]
    )
    assert "fewer than 11" in artifact["limitations"]["privacy_suppression"].lower()
    assert artifact["row_validation"]["quarantined_rows"] == 0
    assert artifact["row_validation"]["valid_rows"] == artifact["pagination"]["rows_retrieved"]
    assert artifact["retrieved_at"] == manifest["retrieved_at"]
    assert all("beneficiary" not in json.dumps(row).lower() for row in artifact["aggregates"])


def test_trials_public_artifact_reconciles_total_valid_quarantine_and_missing_enrollment() -> None:
    artifact, manifest = _verified_artifact("clinicaltrials_ckd_landscape")
    counts = artifact["counts"]
    assert artifact["evidence_type"] == "public_observed"
    assert counts["api_total_count"] == 3706
    assert counts["api_total_count"] == counts["valid_count"] + counts["quarantine_count"]
    assert counts["api_total_count"] == counts["retrieved_row_count"]
    assert counts["api_total_count"] == counts["unique_valid_nct_id_count"]
    assert counts["valid_count"] == counts["unique_nct_ids"] == 3706
    assert counts["studies_with_missing_enrollment"] > 0
    assert counts["dimension_denominators"]["intervention_available"] < 3706
    assert counts["dimension_denominators"]["location_available"] < 3706
    assert artifact["intervention"]
    assert artifact["pagination"]["initial_request_url"].startswith(
        "https://clinicaltrials.gov/api/v2/studies?"
    )
    assert len(artifact["pagination"]["page_audit"]) == 4
    assert artifact["retrieved_at"] == manifest["retrieved_at"]
    assert artifact["status"]
    assert artifact["phase_or_type"]
    assert artifact["sponsor"]
    assert artifact["geography"]
    assert artifact["change_over_time"]
    assert all("nct" not in json.dumps(row).lower() for row in artifact["status"])
