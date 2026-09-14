"""ClinicalTrials.gov API v2 normalized snapshot adapter."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from ckd_intelligence.ingestion._common import (
    date_value,
    datetime_value,
    duplicate_keys,
    integer_value,
    load_source,
    result_with_manifest,
    source_record,
    text_value,
    validate_rows,
)
from ckd_intelligence.quality.contracts import IngestionResult, Scalar

REQUIRED = frozenset(
    {
        "nct_id",
        "brief_title",
        "overall_status",
        "phase",
        "enrollment",
        "condition",
        "intervention",
        "sponsor",
        "country",
        "last_update_date",
        "study_type",
    }
)
STATUSES = {
    "NOT_YET_RECRUITING",
    "RECRUITING",
    "ENROLLING_BY_INVITATION",
    "ACTIVE_NOT_RECRUITING",
    "SUSPENDED",
    "TERMINATED",
    "COMPLETED",
    "WITHDRAWN",
    "UNKNOWN",
}
PHASES = {"NA", "EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4"}
STUDY_TYPES = {"INTERVENTIONAL", "OBSERVATIONAL", "EXPANDED_ACCESS"}


def ingest_trials(
    source_path_or_url: str | Path, *, cache_dir: Path | None = Path("data/raw")
) -> IngestionResult:
    """Ingest a bounded normalized ClinicalTrials.gov API snapshot."""

    registry = source_record("clinicaltrials")
    snapshot = load_source(source_path_or_url, registry=registry, cache_dir=cache_dir)
    try:
        document = json.loads(snapshot.payload)
    except json.JSONDecodeError as exc:
        raise ValueError("Source must be valid ClinicalTrials.gov JSON") from exc
    if not isinstance(document, dict):
        raise ValueError("ClinicalTrials.gov source must be a JSON object")
    updated_at = datetime_value(document.get("api_updated_at"), "api_updated_at")
    studies = document.get("studies")
    if not isinstance(studies, list) or not all(isinstance(row, dict) for row in studies):
        raise ValueError("ClinicalTrials.gov studies must be a list of JSON objects")
    rows = cast(list[dict[str, object]], studies)
    for row in rows:
        missing = sorted(REQUIRED - row.keys())
        if missing:
            raise ValueError(f"Missing required columns: {', '.join(missing)}")
    string_rows = [
        {key: str(value) if value is not None else "" for key, value in row.items()}
        for row in rows
    ]
    duplicates = duplicate_keys(string_rows, lambda row: (row["nct_id"].strip(),))

    def validate(row: Mapping[str, str]) -> tuple[dict[str, Scalar], list[str]]:
        reasons: list[str] = []
        nct_id = text_value(row, "nct_id", reasons)
        if re.fullmatch(r"NCT\d{8}", nct_id) is None:
            reasons.append("nct_id:invalid_code")
        title = text_value(row, "brief_title", reasons)
        status = text_value(row, "overall_status", reasons)
        if status not in STATUSES:
            reasons.append("overall_status:invalid_code")
        phase = text_value(row, "phase", reasons)
        if phase not in PHASES:
            reasons.append("phase:invalid_code")
        enrollment = integer_value(row, "enrollment", reasons, minimum=0)
        condition = text_value(row, "condition", reasons)
        intervention = text_value(row, "intervention", reasons)
        sponsor = text_value(row, "sponsor", reasons)
        country = text_value(row, "country", reasons)
        last_update = date_value(row, "last_update_date", reasons)
        study_type = text_value(row, "study_type", reasons)
        if study_type not in STUDY_TYPES:
            reasons.append("study_type:invalid_code")
        if (nct_id,) in duplicates:
            reasons.append("nct_id:duplicate_key")
        return {
            "nct_id": nct_id,
            "brief_title": title,
            "overall_status": status,
            "phase": phase,
            "enrollment": enrollment,
            "condition": condition,
            "intervention": intervention,
            "sponsor": sponsor,
            "country": country,
            "last_update_date": last_update,
            "study_type": study_type,
            "evidence_type": registry.evidence_type,
        }, reasons

    valid, quarantine = validate_rows(string_rows, validate)
    return result_with_manifest(
        registry=registry,
        snapshot=snapshot,
        valid=valid,
        quarantine=quarantine,
        coverage_values=(str(row["last_update_date"]) for row in valid),
        source_updated_at=updated_at,
    )
