"""MEPS HC-243 2022 full-year consolidated person-year ingestion."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Mapping
from importlib import import_module
from pathlib import Path
from typing import Any

from ckd_intelligence.ingestion._common import (
    duplicate_keys,
    integer_value,
    load_source,
    native_scalar_text,
    number_value,
    parse_csv,
    require_release_identity,
    result_with_manifest,
    source_record,
    text_value,
    validate_rows,
)
from ckd_intelligence.quality.contracts import (
    ImmutableBatch,
    IngestionResult,
    QuarantineRecord,
    Scalar,
)

REQUIRED = frozenset(
    {
        "source_release",
        "person_id",
        "year",
        "dcs_eligible",
        "diabetes_reported",
        "kidney_problem_proxy",
        "total_expenditure_usd",
        "office_visits",
        "outpatient_visits",
        "emergency_visits",
        "inpatient_stays",
        "prescription_medicines",
        "person_weight",
        "proxy_weight",
        "variance_stratum",
        "variance_psu",
    }
)
MAX_SOURCE_BYTES = 750 * 1024 * 1024
SURVEY_MISSING = frozenset({"-1", "-2", "-7", "-8", "-9", "-15"})
NATIVE_REQUIRED = {
    "DUPERSID",
    "DATAYEAR",
    "DCSELIG",
    "DSDIA53",
    "DSKIDN53",
    "TOTEXP22",
    "OBTOTV22",
    "OPTOTV22",
    "ERTOT22",
    "IPDIS22",
    "RXTOT22",
    "PERWT22F",
    "DIABW22F",
    "VARSTR",
    "VARPSU",
}

# Official H243.DAT fixed-width positions from the AHRQ Stata programming file.
FIXED_WIDTHS: dict[str, tuple[int, int]] = {
    "DUPERSID": (11, 20),
    "DATAYEAR": (23, 26),
    "DCSELIG": (836, 836),
    "DSDIA53": (837, 838),
    "DSKIDN53": (902, 904),
    "TOTEXP22": (2616, 2622),
    "OBTOTV22": (2691, 2693),
    "OPTOTV22": (2852, 2854),
    "ERTOT22": (3188, 3189),
    "IPDIS22": (3385, 3385),
    "RXTOT22": (3925, 3927),
    "PERWT22F": (4001, 4013),
    "DIABW22F": (4053, 4065),
    "VARSTR": (4066, 4069),
    "VARPSU": (4070, 4070),
}


def _fixed_value(line: str, field: str) -> str:
    start, end = FIXED_WIDTHS[field]
    return line[start - 1 : end].strip()


def _native_meps_ascii_rows(payload: bytes) -> list[dict[str, str]]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = [
            info
            for info in archive.infolist()
            if not info.is_dir() and info.filename.lower().endswith(".dat")
        ]
        if len(members) != 1:
            raise ValueError("Native MEPS ZIP must contain exactly one H243 DAT file")
        text = archive.read(members[0]).decode("latin-1")
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        source = {field: _fixed_value(line, field) for field in FIXED_WIDTHS}
        rows.append(
            {
                "source_release": "HC-243-2022",
                "person_id": source["DUPERSID"],
                "year": source["DATAYEAR"],
                "dcs_eligible": source["DCSELIG"],
                "diabetes_reported": source["DSDIA53"],
                "kidney_problem_proxy": source["DSKIDN53"],
                "total_expenditure_usd": source["TOTEXP22"],
                "office_visits": source["OBTOTV22"],
                "outpatient_visits": source["OPTOTV22"],
                "emergency_visits": source["ERTOT22"],
                "inpatient_stays": source["IPDIS22"],
                "prescription_medicines": source["RXTOT22"],
                "person_weight": source["PERWT22F"],
                "proxy_weight": source["DIABW22F"],
                "variance_stratum": source["VARSTR"],
                "variance_psu": source["VARPSU"],
            }
        )
    return rows


def _native_meps_xpt_rows(payload: bytes) -> list[dict[str, str]]:
    try:
        pandas: Any = import_module("pandas")
    except ImportError as exc:
        raise RuntimeError("MEPS native ingestion requires the pandas runtime dependency") from exc
    frame = pandas.read_sas(io.BytesIO(payload), format="xport")
    missing = sorted(NATIVE_REQUIRED - set(frame.columns))
    if missing:
        raise ValueError(f"Missing required native MEPS columns: {', '.join(missing)}")
    rows: list[dict[str, str]] = []
    for row in frame.to_dict(orient="records"):
        rows.append(
            {
                "source_release": "HC-243-2022",
                "person_id": native_scalar_text(row["DUPERSID"]),
                "year": native_scalar_text(row["DATAYEAR"]),
                "dcs_eligible": native_scalar_text(row["DCSELIG"]),
                "diabetes_reported": native_scalar_text(row["DSDIA53"]),
                "kidney_problem_proxy": native_scalar_text(row["DSKIDN53"]),
                "total_expenditure_usd": native_scalar_text(row["TOTEXP22"]),
                "office_visits": native_scalar_text(row["OBTOTV22"]),
                "outpatient_visits": native_scalar_text(row["OPTOTV22"]),
                "emergency_visits": native_scalar_text(row["ERTOT22"]),
                "inpatient_stays": native_scalar_text(row["IPDIS22"]),
                "prescription_medicines": native_scalar_text(row["RXTOT22"]),
                "person_weight": native_scalar_text(row["PERWT22F"]),
                "proxy_weight": native_scalar_text(row["DIABW22F"]),
                "variance_stratum": native_scalar_text(row["VARSTR"]),
                "variance_psu": native_scalar_text(row["VARPSU"]),
            }
        )
    return rows


def _native_meps_rows(payload: bytes) -> list[dict[str, str]]:
    """Normalize the official HC-243 2022 native DAT or transport layout."""

    if payload.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return _native_meps_ascii_rows(payload)
    return _native_meps_xpt_rows(payload)


def _survey_number(
    row: Mapping[str, str], field: str, reasons: list[str], *, integer: bool = False
) -> int | float | None:
    value = row[field].strip()
    if value.upper() in {"", ".", "NA", "N/A", "NULL", "NONE"} | SURVEY_MISSING:
        return None
    try:
        parsed: int | float = int(value) if integer else float(value)
    except ValueError:
        reasons.append(f"{field}:invalid_number")
        return None
    if isinstance(parsed, float) and parsed != parsed:
        reasons.append(f"{field}:invalid_number")
        return None
    if parsed < 0:
        reasons.append(f"{field}:out_of_range")
        return None
    return parsed


def _validate_rows(
    rows: list[dict[str, str]], release: str
) -> tuple[ImmutableBatch, tuple[QuarantineRecord, ...]]:
    registry = source_record("meps")
    require_release_identity(rows, "source_release", release)
    duplicates = duplicate_keys(rows, lambda row: (row["person_id"].strip(),))

    def validate(row: Mapping[str, str]) -> tuple[dict[str, Scalar], list[str]]:
        reasons: list[str] = []
        source_release = text_value(row, "source_release", reasons)
        if source_release != release:
            reasons.append("source_release:mismatch")
        person_id = text_value(row, "person_id", reasons)
        year = integer_value(row, "year", reasons, minimum=2022, maximum=2022)
        dcs = integer_value(row, "dcs_eligible", reasons, minimum=0, maximum=2)
        diabetes = integer_value(
            row,
            "diabetes_reported",
            reasons,
            minimum=-15,
            maximum=2,
        )
        kidney = integer_value(
            row,
            "kidney_problem_proxy",
            reasons,
            minimum=-15,
            maximum=2,
        )
        expenditure = _survey_number(row, "total_expenditure_usd", reasons)
        visits = {
            field: _survey_number(row, field, reasons, integer=True)
            for field in (
                "office_visits",
                "outpatient_visits",
                "emergency_visits",
                "inpatient_stays",
                "prescription_medicines",
            )
        }
        person_weight = number_value(row, "person_weight", reasons, minimum=0.0)
        proxy_weight = number_value(row, "proxy_weight", reasons, minimum=0.0)
        variance_stratum = integer_value(row, "variance_stratum", reasons, minimum=1)
        variance_psu = integer_value(row, "variance_psu", reasons, minimum=1)
        if (person_id,) in duplicates:
            reasons.append("person_id:duplicate_key")
        return {
            "source_release": source_release,
            "person_id": person_id,
            "year": year,
            "dcs_eligible": dcs,
            "diabetes_reported": diabetes,
            "kidney_problem_proxy": kidney,
            "total_expenditure_usd": expenditure,
            **visits,
            "person_weight": person_weight,
            "proxy_weight": proxy_weight,
            "variance_stratum": variance_stratum,
            "variance_psu": variance_psu,
            "evidence_type": registry.evidence_type,
        }, reasons

    return validate_rows(rows, validate)


def ingest_meps(
    source_path_or_url: str | Path, *, cache_dir: Path | None = Path("data/raw")
) -> IngestionResult:
    """Ingest HC-243 2022 person-year records with survey design metadata."""

    registry = source_record("meps")
    snapshot = load_source(
        source_path_or_url, registry=registry, cache_dir=cache_dir, max_bytes=MAX_SOURCE_BYTES
    )
    if snapshot.suffix in {".zip", ".xpt"}:
        if "h243" not in snapshot.source_uri.lower():
            raise ValueError("Native MEPS source locator must identify HC-243")
        rows = _native_meps_rows(snapshot.payload)
    else:
        rows = parse_csv(snapshot.payload, REQUIRED)
    valid, quarantine = _validate_rows(rows, registry.version)
    return result_with_manifest(
        registry=registry,
        snapshot=snapshot,
        valid=valid,
        quarantine=quarantine,
        coverage_values=(str(row["year"]) for row in valid),
    )
