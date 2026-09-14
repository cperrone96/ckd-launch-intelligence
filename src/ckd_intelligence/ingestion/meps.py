"""MEPS person/event public-use fixture adapter."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ckd_intelligence.ingestion._common import (
    duplicate_keys,
    integer_value,
    load_source,
    number_value,
    parse_csv,
    result_with_manifest,
    source_record,
    text_value,
    validate_rows,
)
from ckd_intelligence.quality.contracts import IngestionResult, Scalar

REQUIRED = frozenset(
    {
        "event_id",
        "person_id",
        "year",
        "condition_code",
        "event_type",
        "rx_name",
        "expenditure_usd",
        "person_weight",
        "variance_stratum",
        "variance_psu",
    }
)
EVENT_TYPES = {"office_visit", "outpatient", "inpatient", "emergency", "prescription"}


def ingest_meps(
    source_path_or_url: str | Path, *, cache_dir: Path | None = Path("data/raw")
) -> IngestionResult:
    """Ingest normalized MEPS events while preserving weights and design variables."""

    registry = source_record("meps")
    snapshot = load_source(source_path_or_url, registry=registry, cache_dir=cache_dir)
    rows = parse_csv(snapshot.payload, REQUIRED)
    duplicates = duplicate_keys(rows, lambda row: (row["event_id"].strip(),))

    def validate(row: Mapping[str, str]) -> tuple[dict[str, Scalar], list[str]]:
        reasons: list[str] = []
        event_id = text_value(row, "event_id", reasons)
        person_id = text_value(row, "person_id", reasons)
        year = integer_value(row, "year", reasons, minimum=1996, maximum=2100)
        condition = text_value(row, "condition_code", reasons)
        event_type = text_value(row, "event_type", reasons)
        if event_type not in EVENT_TYPES:
            reasons.append("event_type:invalid_code")
        rx_name = row["rx_name"].strip() or None
        expenditure = number_value(row, "expenditure_usd", reasons, minimum=0)
        weight = number_value(row, "person_weight", reasons, minimum=0.000001)
        stratum = integer_value(row, "variance_stratum", reasons, minimum=1)
        psu = integer_value(row, "variance_psu", reasons, minimum=1)
        if (event_id,) in duplicates:
            reasons.append("event_id:duplicate_key")
        return {
            "event_id": event_id,
            "person_id": person_id,
            "year": year,
            "condition_code": condition,
            "event_type": event_type,
            "rx_name": rx_name,
            "expenditure_usd": expenditure,
            "person_weight": weight,
            "variance_stratum": stratum,
            "variance_psu": psu,
            "evidence_type": registry.evidence_type,
        }, reasons

    valid, quarantine = validate_rows(rows, validate)
    return result_with_manifest(
        registry=registry,
        snapshot=snapshot,
        valid=valid,
        quarantine=quarantine,
        coverage_values=(str(row["year"]) for row in valid),
    )
