"""CMS DE-SynPUF synthetic claims fixture adapter."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from pathlib import Path

from ckd_intelligence.ingestion._common import (
    date_value,
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
        "beneficiary_id",
        "claim_id",
        "claim_type",
        "service_from_date",
        "service_through_date",
        "diagnosis_code",
        "provider_id",
        "payment_amount_usd",
        "year",
    }
)
CLAIM_TYPES = {"inpatient", "outpatient", "carrier", "prescription"}


def ingest_synpuf(
    source_path_or_url: str | Path, *, cache_dir: Path | None = Path("data/raw")
) -> IngestionResult:
    """Ingest synthetic claims while permanently labeling their evidence boundary."""

    registry = source_record("synpuf")
    snapshot = load_source(source_path_or_url, registry=registry, cache_dir=cache_dir)
    rows = parse_csv(snapshot.payload, REQUIRED)
    duplicates = duplicate_keys(rows, lambda row: (row["claim_id"].strip(),))

    def validate(row: Mapping[str, str]) -> tuple[dict[str, Scalar], list[str]]:
        reasons: list[str] = []
        beneficiary_id = text_value(row, "beneficiary_id", reasons)
        claim_id = text_value(row, "claim_id", reasons)
        claim_type = text_value(row, "claim_type", reasons)
        if claim_type not in CLAIM_TYPES:
            reasons.append("claim_type:invalid_code")
        from_date = date_value(row, "service_from_date", reasons)
        through_date = date_value(row, "service_through_date", reasons)
        try:
            if date.fromisoformat(from_date) > date.fromisoformat(through_date):
                reasons.append("service_date_range:invalid_range")
        except ValueError:
            pass
        diagnosis = text_value(row, "diagnosis_code", reasons)
        provider = text_value(row, "provider_id", reasons)
        payment = number_value(row, "payment_amount_usd", reasons, minimum=0)
        year = integer_value(row, "year", reasons, minimum=2008, maximum=2010)
        if (claim_id,) in duplicates:
            reasons.append("claim_id:duplicate_key")
        return {
            "beneficiary_id": beneficiary_id,
            "claim_id": claim_id,
            "claim_type": claim_type,
            "service_from_date": from_date,
            "service_through_date": through_date,
            "diagnosis_code": diagnosis,
            "provider_id": provider,
            "payment_amount_usd": payment,
            "year": year,
            "evidence_type": registry.evidence_type,
        }, reasons

    valid, quarantine = validate_rows(rows, validate)
    return result_with_manifest(
        registry=registry,
        snapshot=snapshot,
        valid=valid,
        quarantine=quarantine,
        coverage_values=(str(row["service_from_date"]) for row in valid),
    )
