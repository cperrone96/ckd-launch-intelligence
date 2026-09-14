"""ClinicalTrials.gov API v2 snapshot adapter."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ckd_intelligence.ingestion._common import load_source, result_with_manifest, source_record
from ckd_intelligence.quality.contracts import (
    ImmutableBatch,
    IngestionResult,
    QuarantineRecord,
    Scalar,
)

CKD_QUERY = 'AREA[ConditionSearch]("Chronic Kidney Disease")'
MAX_SOURCE_BYTES = 100 * 1024 * 1024
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
    "WITHHELD",
    "NO_LONGER_AVAILABLE",
    "TEMPORARILY_NOT_AVAILABLE",
    "APPROVED_FOR_MARKETING",
    "AVAILABLE",
}
PHASES = {"NA", "EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4"}
STUDY_TYPES = {"INTERVENTIONAL", "OBSERVATIONAL", "EXPANDED_ACCESS"}


def _object(value: object, field: str, reasons: list[str]) -> Mapping[str, object] | None:
    if not isinstance(value, dict):
        reasons.append(f"{field}:invalid_type")
        return None
    return value


def _optional_object(
    container: Mapping[str, object], key: str, field: str, reasons: list[str]
) -> Mapping[str, object] | None:
    """Return an optional API module without treating omission as corruption."""

    value = container.get(key)
    if value is None:
        return None
    return _object(value, field, reasons)


def _string(container: Mapping[str, object], key: str, field: str, reasons: list[str]) -> str:
    value = container.get(key)
    if not isinstance(value, str):
        reasons.append(f"{field}:invalid_type")
        return ""
    if not value.strip():
        reasons.append(f"{field}:missing_sentinel")
    return value.strip()


def _integer(
    container: Mapping[str, object], key: str, field: str, reasons: list[str]
) -> int | None:
    value = container.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        reasons.append(f"{field}:invalid_type")
        return None
    if value < 0:
        reasons.append(f"{field}:out_of_range")
    return value


def _strings(
    container: Mapping[str, object], key: str, field: str, reasons: list[str]
) -> list[str]:
    value = container.get(key)
    if not isinstance(value, list) or not value:
        reasons.append(f"{field}:invalid_type")
        return []
    if any(not isinstance(item, str) or not item.strip() for item in value):
        reasons.append(f"{field}:invalid_type")
        return []
    return [item.strip() for item in value]


def _nested_names(
    container: Mapping[str, object], key: str, field: str, reasons: list[str]
) -> list[str] | None:
    value = container.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        reasons.append(f"{field}:invalid_type")
        return None
    names: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            reasons.append(f"{field}:invalid_type")
            return None
        if "name" not in item:
            return None
        if not isinstance(item.get("name"), str):
            reasons.append(f"{field}:invalid_type")
            return None
        name = item["name"].strip()
        if not name:
            reasons.append(f"{field}:missing_sentinel")
        names.append(name)
    return names


def _nested_countries(container: Mapping[str, object], reasons: list[str]) -> list[str] | None:
    value = container.get("locations")
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        reasons.append("country:invalid_type")
        return None
    countries: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            reasons.append("country:invalid_type")
            return None
        if "country" not in item:
            return None
        if not isinstance(item.get("country"), str):
            reasons.append("country:invalid_type")
            return None
        country = item["country"].strip()
        if not country:
            reasons.append("country:missing_sentinel")
        countries.append(country)
    return sorted(set(countries))


def _normalize_study(study: object) -> tuple[dict[str, Scalar], list[str], str]:
    raw_json = json.dumps(study, sort_keys=True, separators=(",", ":"))
    reasons: list[str] = []
    if not isinstance(study, dict):
        return {}, ["study:invalid_type"], raw_json
    protocol = _object(study.get("protocolSection"), "protocolSection", reasons)
    if protocol is None:
        return {}, reasons, raw_json

    identification = (
        _object(protocol.get("identificationModule"), "identificationModule", reasons) or {}
    )
    status_module = _object(protocol.get("statusModule"), "statusModule", reasons) or {}
    design = _object(protocol.get("designModule"), "designModule", reasons) or {}
    conditions = _object(protocol.get("conditionsModule"), "conditionsModule", reasons) or {}
    arms = _optional_object(protocol, "armsInterventionsModule", "armsInterventionsModule", reasons)
    sponsors = (
        _object(
            protocol.get("sponsorCollaboratorsModule"),
            "sponsorCollaboratorsModule",
            reasons,
        )
        or {}
    )
    locations = _optional_object(
        protocol, "contactsLocationsModule", "contactsLocationsModule", reasons
    )

    nct_id = _string(identification, "nctId", "nct_id", reasons)
    if re.fullmatch(r"NCT\d{8}", nct_id) is None:
        reasons.append("nct_id:invalid_code")
    title = _string(identification, "briefTitle", "brief_title", reasons)
    status = _string(status_module, "overallStatus", "overall_status", reasons)
    if status not in STATUSES:
        reasons.append("overall_status:invalid_code")
    update_struct = (
        _object(status_module.get("lastUpdatePostDateStruct"), "lastUpdatePostDateStruct", reasons)
        or {}
    )
    last_update = _string(update_struct, "date", "last_update_date", reasons)
    try:
        date.fromisoformat(last_update)
    except ValueError:
        reasons.append("last_update_date:invalid_date")

    study_type = _string(design, "studyType", "study_type", reasons)
    if study_type not in STUDY_TYPES:
        reasons.append("study_type:invalid_code")
    phases_value = design.get("phases")
    if phases_value in (None, []) and study_type in {"OBSERVATIONAL", "EXPANDED_ACCESS"}:
        phases = ["NA"]
    elif phases_value in (None, []):
        phases = []
    elif not isinstance(phases_value, list):
        reasons.append("phase:invalid_type")
        phases = []
    else:
        phases = _strings(design, "phases", "phase", reasons)
    if any(phase not in PHASES for phase in phases):
        reasons.append("phase:invalid_code")
    raw_enrollment_info = design.get("enrollmentInfo")
    if raw_enrollment_info is None:
        # ClinicalTrials.gov permits studies to omit enrollment.  Preserve that
        # source omission as null instead of turning it into an invalid record.
        enrollment_info: Mapping[str, object] = {}
    else:
        enrollment_info = _object(raw_enrollment_info, "enrollmentInfo", reasons) or {}
    enrollment = (
        None
        if "count" not in enrollment_info or enrollment_info.get("count") is None
        else _integer(enrollment_info, "count", "enrollment", reasons)
    )
    condition_values = _strings(conditions, "conditions", "condition", reasons)
    interventions = (
        None if arms is None else _nested_names(arms, "interventions", "intervention", reasons)
    )
    lead_sponsor = _object(sponsors.get("leadSponsor"), "leadSponsor", reasons) or {}
    sponsor = _string(lead_sponsor, "name", "sponsor", reasons)
    countries = None if locations is None else _nested_countries(locations, reasons)

    return (
        {
            "nct_id": nct_id,
            "brief_title": title,
            "overall_status": status,
            "phase": "|".join(phases) or None,
            "enrollment": enrollment,
            "condition": " | ".join(condition_values),
            "intervention": None if interventions is None else " | ".join(interventions),
            "sponsor": sponsor,
            "country": None if countries is None else " | ".join(countries),
            "last_update_date": last_update,
            "study_type": study_type,
            "evidence_type": "public_observed",
        },
        reasons,
        raw_json,
    )


def _snapshot_timestamp(
    metadata: Mapping[str, object], registry_date: date
) -> tuple[str, datetime]:
    if metadata.get("api_version") != "v2":
        raise ValueError("ClinicalTrials.gov snapshot must identify API version v2")
    if metadata.get("query") != CKD_QUERY:
        raise ValueError("ClinicalTrials.gov snapshot must preserve the exact documented CKD query")
    value = metadata.get("retrieved_at")
    if not isinstance(value, str):
        raise ValueError("retrieved_at must be an ISO 8601 timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("retrieved_at must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("retrieved_at must include a timezone")
    parsed_utc = parsed.astimezone(UTC)
    if parsed_utc.date() > registry_date:
        raise ValueError("retrieved_at cannot be after the registered retrieval date")
    return value, parsed_utc


def ingest_trials(
    source_path_or_url: str | Path, *, cache_dir: Path | None = Path("data/raw")
) -> IngestionResult:
    """Ingest a dated envelope containing native ClinicalTrials.gov API-v2 studies."""

    registry = source_record("clinicaltrials")
    snapshot = load_source(
        source_path_or_url, registry=registry, cache_dir=cache_dir, max_bytes=MAX_SOURCE_BYTES
    )
    try:
        document: Any = json.loads(snapshot.payload)
    except json.JSONDecodeError as exc:
        raise ValueError("Source must be valid ClinicalTrials.gov JSON") from exc
    if not isinstance(document, dict):
        raise ValueError("ClinicalTrials.gov source must be a JSON object")
    metadata = document.get("snapshot_metadata")
    if not isinstance(metadata, dict):
        raise ValueError("ClinicalTrials.gov snapshot_metadata must be a JSON object")
    updated_at, retrieved = _snapshot_timestamp(metadata, registry.retrieved_at)
    studies = document.get("studies")
    if not isinstance(studies, list):
        raise ValueError("ClinicalTrials.gov studies must be a list")

    normalized = [_normalize_study(study) for study in studies]
    nct_counts = Counter(str(row.get("nct_id", "")) for row, _, _ in normalized)
    valid_rows: list[dict[str, Scalar]] = []
    quarantine: list[QuarantineRecord] = []
    for index, (row, reasons, raw_json) in enumerate(normalized, start=1):
        nct_id = str(row.get("nct_id", ""))
        if nct_id and nct_counts[nct_id] > 1:
            reasons.append("nct_id:duplicate_key")
        last_update = str(row.get("last_update_date", ""))
        try:
            if date.fromisoformat(last_update) > retrieved.date():
                reasons.append("last_update_date:after_snapshot")
        except ValueError:
            pass
        if reasons:
            quarantine.append(
                QuarantineRecord(
                    row_number=index,
                    reasons=tuple(sorted(set(reasons))),
                    raw_record=MappingProxyType({"raw_json": raw_json}),
                )
            )
        else:
            valid_rows.append(row)

    valid = ImmutableBatch.from_records(valid_rows)
    return result_with_manifest(
        registry=registry,
        snapshot=snapshot,
        valid=valid,
        quarantine=tuple(quarantine),
        coverage_values=(str(row["last_update_date"]) for row in valid),
        source_updated_at=updated_at,
    )
