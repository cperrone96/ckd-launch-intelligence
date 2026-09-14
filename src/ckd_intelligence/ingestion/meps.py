"""MEPS person/event public-use ingestion adapter."""

from __future__ import annotations

import re
from collections.abc import Mapping
from importlib import import_module
from io import BytesIO
from pathlib import Path
from typing import Any

from ckd_intelligence.ingestion._common import (
    duplicate_keys,
    integer_value,
    load_source,
    native_scalar_text,
    number_value,
    optional_text_value,
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
MAX_SOURCE_BYTES = 750 * 1024 * 1024
ICD10_PATTERN = re.compile(r"^[A-Z][0-9][0-9A-Z](?:\.?[0-9A-Z]{1,4})?$")
NATIVE_REQUIRED = {"DUPERSID", "TOTEXP21", "PERWT21F", "VARSTR", "VARPSU"}


def _native_meps_rows(payload: bytes) -> list[dict[str, str]]:
    """Normalize the supported HC-243 full-year person-level XPT layout."""

    try:
        pandas: Any = import_module("pandas")
    except ImportError as exc:
        raise RuntimeError("MEPS XPT ingestion requires the pandas runtime dependency") from exc
    frame = pandas.read_sas(BytesIO(payload), format="xport")
    missing = sorted(NATIVE_REQUIRED - set(frame.columns))
    if missing:
        raise ValueError(f"Missing required native MEPS columns: {', '.join(missing)}")
    records: list[dict[str, str]] = []
    for row in frame.to_dict(orient="records"):
        records.append(
            {
                "source_release": "HC-243-2021",
                "person_id": native_scalar_text(row["DUPERSID"]),
                "year": "2021",
                "total_expenditure_usd": native_scalar_text(row["TOTEXP21"]),
                "person_weight": native_scalar_text(row["PERWT21F"]),
                "variance_stratum": native_scalar_text(row["VARSTR"]),
                "variance_psu": native_scalar_text(row["VARPSU"]),
            }
        )
    return records


def ingest_meps(
    source_path_or_url: str | Path, *, cache_dir: Path | None = Path("data/raw")
) -> IngestionResult:
    """Ingest normalized MEPS events while preserving weights and design variables."""

    registry = source_record("meps")
    snapshot = load_source(
        source_path_or_url,
        registry=registry,
        cache_dir=cache_dir,
        max_bytes=MAX_SOURCE_BYTES,
    )
    if snapshot.suffix == ".xpt":
        if "h243" not in snapshot.source_uri.lower():
            raise ValueError("Native MEPS source locator must identify HC-243")
        native = _native_meps_rows(snapshot.payload)
        require_release_identity(native, "source_release", registry.version)
        duplicates = duplicate_keys(native, lambda row: (row["person_id"],))

        def validate_native(row: Mapping[str, str]) -> tuple[dict[str, Scalar], list[str]]:
            reasons: list[str] = []
            release = text_value(row, "source_release", reasons)
            if release != registry.version:
                reasons.append("source_release:mismatch")
            person_id = text_value(row, "person_id", reasons)
            if (person_id,) in duplicates:
                reasons.append("person_id:duplicate_key")
            year = integer_value(row, "year", reasons, minimum=2021, maximum=2021)
            total = number_value(row, "total_expenditure_usd", reasons, minimum=0)
            weight = number_value(row, "person_weight", reasons, minimum=0.000001)
            stratum = integer_value(row, "variance_stratum", reasons, minimum=1)
            psu = integer_value(row, "variance_psu", reasons, minimum=1)
            return {
                "source_release": release,
                "person_id": person_id,
                "year": year,
                "total_expenditure_usd": total,
                "person_weight": weight,
                "variance_stratum": stratum,
                "variance_psu": psu,
                "evidence_type": registry.evidence_type,
            }, reasons

        valid, quarantine = validate_rows(native, validate_native)
        return result_with_manifest(
            registry=registry,
            snapshot=snapshot,
            valid=valid,
            quarantine=quarantine,
            coverage_values=("2021",),
        )
    rows = parse_csv(snapshot.payload, REQUIRED)
    require_release_identity(rows, "source_release", registry.version)
    duplicates = duplicate_keys(rows, lambda row: (row["event_id"].strip(),))

    def validate(row: Mapping[str, str]) -> tuple[dict[str, Scalar], list[str]]:
        reasons: list[str] = []
        release = text_value(row, "source_release", reasons)
        if release != registry.version:
            reasons.append("source_release:mismatch")
        event_id = text_value(row, "event_id", reasons)
        person_id = text_value(row, "person_id", reasons)
        year = integer_value(row, "year", reasons, minimum=1996, maximum=2100)
        condition = text_value(row, "condition_code", reasons)
        if ICD10_PATTERN.fullmatch(condition) is None:
            reasons.append("condition_code:invalid_code")
        event_type = text_value(row, "event_type", reasons)
        if event_type not in EVENT_TYPES:
            reasons.append("event_type:invalid_code")
        rx_name = optional_text_value(row, "rx_name")
        expenditure = number_value(row, "expenditure_usd", reasons, minimum=0)
        weight = number_value(row, "person_weight", reasons, minimum=0.000001)
        stratum = integer_value(row, "variance_stratum", reasons, minimum=1)
        psu = integer_value(row, "variance_psu", reasons, minimum=1)
        if year != 2021:
            reasons.append("year:outside_release")
        if (event_id,) in duplicates:
            reasons.append("event_id:duplicate_key")
        return {
            "source_release": release,
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
