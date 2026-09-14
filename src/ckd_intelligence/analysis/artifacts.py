"""Fail-closed output paths for public-observed and fixture analyses."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Literal

PatientNeedEvidence = Literal["public_observed", "fixture_only"]


def patient_need_output_paths(
    data_root: Path, evidence_type: PatientNeedEvidence
) -> tuple[Path, Path]:
    """Keep fixture-only output physically separate from official aggregates."""

    if evidence_type == "public_observed":
        directory = data_root / "processed"
        stem = "patient_need_summary"
    elif evidence_type == "fixture_only":
        directory = data_root / "processed" / "fixture"
        stem = "patient_need_summary_fixture"
    else:
        raise ValueError(f"unsupported patient-need evidence type: {evidence_type}")
    return directory / f"{stem}.json", directory / f"{stem}.sha256"


def patient_finding_output_paths(
    data_root: Path, evidence_type: PatientNeedEvidence
) -> tuple[Path, Path]:
    """Keep fixture model output physically separate from official model aggregates."""

    if evidence_type == "public_observed":
        directory = data_root / "processed"
        stem = "patient_finding_model_comparison"
    elif evidence_type == "fixture_only":
        directory = data_root / "processed" / "fixture"
        stem = "patient_finding_model_comparison_fixture"
    else:
        raise ValueError(f"unsupported patient-finding evidence type: {evidence_type}")
    return directory / f"{stem}.json", directory / f"{stem}.sha256"


def patient_finding_source_provenance(
    data_root: Path, evidence_type: PatientNeedEvidence
) -> dict[str, object]:
    """Describe the source actually used by the patient-finding notebook."""

    if evidence_type == "public_observed":
        relative_path = Path("data/manifests/nhanes-2017-2018-patient-need.json")
        manifest_path = data_root / "manifests" / relative_path.name
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return {
            "evidence_type": evidence_type,
            "path": relative_path.as_posix(),
            "source": manifest["source"],
            "release": manifest["release"],
            "retrieved_at": manifest["retrieved_at"],
            "join_policy": (
                "Documented one-to-one within-cycle NHANES component join; "
                "no cross-source or cross-person linkage"
            ),
            "files": [
                {key: item[key] for key in ("name", "url", "sha256", "bytes")}
                for item in manifest["files"]
            ],
        }
    if evidence_type == "fixture_only":
        relative_path = Path("data/fixtures/nhanes_patient_need_representative.csv")
        fixture_path = data_root / "fixtures" / relative_path.name
        payload = fixture_path.read_bytes()
        return {
            "evidence_type": evidence_type,
            "path": relative_path.as_posix(),
            "source": "Deterministic modeling fixture; not public-observed evidence",
            "sha256": sha256(payload).hexdigest(),
            "bytes": len(payload),
            "transformation": (
                "Notebook-only deterministic expansion; never written to the "
                "public-observed namespace"
            ),
        }
    raise ValueError(f"unsupported patient-finding evidence type: {evidence_type}")
