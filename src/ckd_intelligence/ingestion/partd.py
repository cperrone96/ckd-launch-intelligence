"""CMS Medicare Part D aggregate public-use fixture adapter."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from ckd_intelligence.ingestion._common import (
    duplicate_keys,
    integer_value,
    load_source,
    number_value,
    parse_csv,
    reject_forbidden_fields,
    result_with_manifest,
    source_record,
    text_value,
    validate_rows,
)
from ckd_intelligence.quality.contracts import IngestionResult, Scalar

REQUIRED = frozenset(
    {
        "provider_npi",
        "provider_state",
        "drug_name",
        "generic_name",
        "total_claim_count",
        "total_30_day_fill_count",
        "total_drug_cost_usd",
        "year",
    }
)
FORBIDDEN = frozenset({"beneficiary_id", "patient_id", "person_id"})


def ingest_partd(
    source_path_or_url: str | Path, *, cache_dir: Path | None = Path("data/raw")
) -> IngestionResult:
    """Ingest provider/drug aggregates without beneficiary-level interpretation."""

    registry = source_record("partd")
    snapshot = load_source(source_path_or_url, registry=registry, cache_dir=cache_dir)
    rows = parse_csv(snapshot.payload, REQUIRED)
    reject_forbidden_fields(rows, FORBIDDEN)
    def key(row: Mapping[str, str]) -> tuple[str, ...]:
        return (
            row["provider_npi"].strip(),
            row["drug_name"].strip(),
            row["year"].strip(),
        )

    duplicates = duplicate_keys(rows, key)

    def validate(row: Mapping[str, str]) -> tuple[dict[str, Scalar], list[str]]:
        reasons: list[str] = []
        npi = text_value(row, "provider_npi", reasons)
        if re.fullmatch(r"\d{10}", npi) is None:
            reasons.append("provider_npi:invalid_code")
        state = text_value(row, "provider_state", reasons)
        if re.fullmatch(r"[A-Z]{2}", state) is None:
            reasons.append("provider_state:invalid_code")
        drug = text_value(row, "drug_name", reasons)
        generic = text_value(row, "generic_name", reasons)
        claims = integer_value(row, "total_claim_count", reasons, minimum=0)
        fills = number_value(row, "total_30_day_fill_count", reasons, minimum=0)
        cost = number_value(row, "total_drug_cost_usd", reasons, minimum=0)
        year = integer_value(row, "year", reasons, minimum=2024, maximum=2024)
        if key(row) in duplicates:
            reasons.append("record_key:duplicate_key")
        return {
            "provider_npi": npi,
            "provider_state": state,
            "drug_name": drug,
            "generic_name": generic,
            "total_claim_count": claims,
            "total_30_day_fill_count": fills,
            "total_drug_cost_usd": cost,
            "year": year,
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
