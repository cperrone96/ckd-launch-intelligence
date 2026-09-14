from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).parents[2]


def _verified_artifact(stem: str) -> tuple[dict[str, Any], dict[str, Any]]:
    artifact_path = ROOT / "data" / "processed" / f"{stem}.json"
    checksum_path = ROOT / "data" / "processed" / f"{stem}.sha256"
    manifest_path = ROOT / "data" / "manifests" / f"{stem}.json"
    assert artifact_path.exists(), artifact_path
    assert checksum_path.exists(), checksum_path
    assert manifest_path.exists(), manifest_path
    digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    assert digest in checksum_path.read_text(encoding="utf-8")
    return (
        cast(dict[str, Any], json.loads(artifact_path.read_text(encoding="utf-8"))),
        cast(dict[str, Any], json.loads(manifest_path.read_text(encoding="utf-8"))),
    )


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
    assert artifact["retrieved_at"] == manifest["retrieved_at"]
    assert all("beneficiary" not in json.dumps(row).lower() for row in artifact["aggregates"])


def test_trials_public_artifact_reconciles_total_valid_quarantine_and_missing_enrollment() -> None:
    artifact, manifest = _verified_artifact("clinicaltrials_ckd_landscape")
    counts = artifact["counts"]
    assert artifact["evidence_type"] == "public_observed"
    assert counts["api_total_count"] == counts["valid_count"] + counts["quarantine_count"]
    assert counts["unique_nct_ids"] == counts["api_total_count"]
    assert counts["studies_with_missing_enrollment"] > 0
    assert artifact["retrieved_at"] == manifest["retrieved_at"]
    assert artifact["status"]
    assert artifact["phase_or_type"]
    assert artifact["sponsor"]
    assert artifact["geography"]
    assert artifact["change_over_time"]
    assert all("nct" not in json.dumps(row).lower() for row in artifact["status"])
