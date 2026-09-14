"""CMS Medicare Part D aggregate public-use ingestion adapter."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from ckd_intelligence.ingestion._common import (
    csv_payload_from_snapshot,
    duplicate_keys,
    integer_value,
    load_source,
    number_value,
    parse_csv,
    reject_forbidden_fields,
    require_release_identity,
    result_with_manifest,
    source_record,
    text_value,
    validate_rows,
)
from ckd_intelligence.quality.contracts import IngestionResult, Scalar

REQUIRED = frozenset(
    {
        "source_release",
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
MAX_SOURCE_BYTES = 256 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
US_POSTAL_CODES = {
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "DC",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
    "AS",
    "GU",
    "MP",
    "PR",
    "VI",
    "UM",
    "FM",
    "MH",
    "PW",
}
NATIVE_REQUIRED = frozenset(
    {
        "Prscrbr_NPI",
        "Prscrbr_State_Abrvtn",
        "Brnd_Name",
        "Gnrc_Name",
        "Tot_Clms",
        "Tot_30day_Fills",
        "Tot_Drug_Cst",
    }
)


def _rows_from_payload(payload: bytes, source_uri: str) -> list[dict[str, str]]:
    header = payload.decode("utf-8-sig", errors="strict").splitlines()[0].split(",")
    if "source_release" in header:
        return parse_csv(payload, REQUIRED)
    if "2024" not in source_uri:
        raise ValueError("Native Part D source locator must identify the registered 2024 release")
    native = parse_csv(payload, NATIVE_REQUIRED)
    return [
        {
            "source_release": "2024",
            "provider_npi": row["Prscrbr_NPI"],
            "provider_state": row["Prscrbr_State_Abrvtn"],
            "drug_name": row["Brnd_Name"],
            "generic_name": row["Gnrc_Name"],
            "total_claim_count": row["Tot_Clms"],
            "total_30_day_fill_count": row["Tot_30day_Fills"],
            "total_drug_cost_usd": row["Tot_Drug_Cst"],
            "year": "2024",
            **(
                {"_ingestion_error": row["_ingestion_error"]} if row.get("_ingestion_error") else {}
            ),
        }
        for row in native
    ]


def ingest_partd(
    source_path_or_url: str | Path, *, cache_dir: Path | None = Path("data/raw")
) -> IngestionResult:
    """Ingest provider/drug aggregates without beneficiary-level interpretation."""

    registry = source_record("partd")
    snapshot = load_source(
        source_path_or_url,
        registry=registry,
        cache_dir=cache_dir,
        max_bytes=MAX_SOURCE_BYTES,
    )
    csv_payload = csv_payload_from_snapshot(snapshot, max_uncompressed_bytes=MAX_UNCOMPRESSED_BYTES)
    rows = _rows_from_payload(csv_payload, snapshot.source_uri)
    require_release_identity(rows, "source_release", registry.version)
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
        release = text_value(row, "source_release", reasons)
        if release != registry.version:
            reasons.append("source_release:mismatch")
        npi = text_value(row, "provider_npi", reasons)
        if re.fullmatch(r"\d{10}", npi) is None:
            reasons.append("provider_npi:invalid_code")
        state = text_value(row, "provider_state", reasons)
        if state not in US_POSTAL_CODES:
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
            "source_release": release,
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
