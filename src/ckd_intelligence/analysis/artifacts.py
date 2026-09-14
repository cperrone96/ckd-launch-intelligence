"""Fail-closed output paths for public-observed and fixture analyses."""

from __future__ import annotations

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
