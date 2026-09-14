"""CMS DE-SynPUF synthetic claims ingestion adapter."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from pathlib import Path

from ckd_intelligence.ingestion._common import (
    csv_payload_from_snapshot,
    date_value,
    duplicate_keys,
    integer_value,
    load_source,
    number_value,
    parse_csv,
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
MAX_SOURCE_BYTES = 512 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
ICD9_PATTERN = re.compile(
    r"^(?:[0-9]{3}(?:\.?[0-9]{1,2})?|V[0-9]{2}(?:\.?[0-9]{1,2})?|"
    r"E[0-9]{3}(?:\.?[0-9])?)$"
)
PROVIDER_PATTERN = re.compile(r"^[A-Z0-9]{1,12}$")
NATIVE_REQUIRED = frozenset(
    {
        "DESYNPUF_ID",
        "CLM_ID",
        "CLM_FROM_DT",
        "CLM_THRU_DT",
        "ADMTNG_ICD9_DGNS_CD",
        "PRVDR_NUM",
        "CLM_PMT_AMT",
    }
)


def _compact_date(value: str) -> str:
    if re.fullmatch(r"\d{8}", value):
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value


def _rows_from_payload(payload: bytes, source_uri: str) -> list[dict[str, str]]:
    header = payload.decode("utf-8-sig", errors="strict").splitlines()[0].split(",")
    if "source_release" in header:
        return parse_csv(payload, REQUIRED)
    locator = source_uri.lower()
    if not any(token in locator for token in {"2008_to_2010", "2008-2010"}):
        raise ValueError("Native DE-SynPUF source locator must identify release 2008-2010")
    claim_type = next((name for name in CLAIM_TYPES if name in locator), None)
    if claim_type is None:
        raise ValueError("Native DE-SynPUF source locator must identify its claim type")
    native = parse_csv(payload, NATIVE_REQUIRED)
    normalized: list[dict[str, str]] = []
    for row in native:
        from_date = _compact_date(row["CLM_FROM_DT"])
        normalized.append(
            {
                "source_release": "2008-2010",
                "beneficiary_id": row["DESYNPUF_ID"],
                "claim_id": row["CLM_ID"],
                "claim_type": claim_type,
                "service_from_date": from_date,
                "service_through_date": _compact_date(row["CLM_THRU_DT"]),
                "diagnosis_code": row["ADMTNG_ICD9_DGNS_CD"],
                "provider_id": row["PRVDR_NUM"],
                "payment_amount_usd": row["CLM_PMT_AMT"],
                "year": from_date[:4],
                **(
                    {"_ingestion_error": row["_ingestion_error"]}
                    if row.get("_ingestion_error")
                    else {}
                ),
            }
        )
    return normalized


def ingest_synpuf(
    source_path_or_url: str | Path, *, cache_dir: Path | None = Path("data/raw")
) -> IngestionResult:
    """Ingest synthetic claims while permanently labeling their evidence boundary."""

    registry = source_record("synpuf")
    snapshot = load_source(
        source_path_or_url,
        registry=registry,
        cache_dir=cache_dir,
        max_bytes=MAX_SOURCE_BYTES,
    )
    csv_payload = csv_payload_from_snapshot(snapshot, max_uncompressed_bytes=MAX_UNCOMPRESSED_BYTES)
    rows = _rows_from_payload(csv_payload, snapshot.source_uri)
    require_release_identity(rows, "source_release", registry.version)
    duplicates = duplicate_keys(rows, lambda row: (row["claim_id"].strip(),))

    def validate(row: Mapping[str, str]) -> tuple[dict[str, Scalar], list[str]]:
        reasons: list[str] = []
        release = text_value(row, "source_release", reasons)
        if release != registry.version:
            reasons.append("source_release:mismatch")
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
        if ICD9_PATTERN.fullmatch(diagnosis) is None:
            reasons.append("diagnosis_code:invalid_code")
        provider = text_value(row, "provider_id", reasons)
        if provider != provider.upper() or PROVIDER_PATTERN.fullmatch(provider) is None:
            reasons.append("provider_id:invalid_code")
        payment = number_value(row, "payment_amount_usd", reasons, minimum=0)
        year = integer_value(row, "year", reasons, minimum=2008, maximum=2010)
        for field, value in (
            ("service_from_date", from_date),
            ("service_through_date", through_date),
        ):
            try:
                if not 2008 <= date.fromisoformat(value).year <= 2010:
                    reasons.append(f"{field}:outside_release")
            except ValueError:
                pass
        try:
            if year is not None and year != date.fromisoformat(from_date).year:
                reasons.append("year:date_mismatch")
        except ValueError:
            pass
        if (claim_id,) in duplicates:
            reasons.append("claim_id:duplicate_key")
        return {
            "source_release": release,
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
