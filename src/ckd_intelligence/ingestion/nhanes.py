"""NHANES participant-level public-use fixture adapter."""

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
        "respondent_id",
        "age_years",
        "sex",
        "race_ethnicity",
        "serum_creatinine_mg_dl",
        "urine_albumin_mg_l",
        "urine_creatinine_mg_dl",
        "sample_weight",
        "strata",
        "psu",
        "survey_cycle",
    }
)


def ingest_nhanes(
    source_path_or_url: str | Path, *, cache_dir: Path | None = Path("data/raw")
) -> IngestionResult:
    """Ingest a normalized NHANES extract while retaining survey design fields."""

    registry = source_record("nhanes")
    snapshot = load_source(source_path_or_url, registry=registry, cache_dir=cache_dir)
    rows = parse_csv(snapshot.payload, REQUIRED)
    duplicates = duplicate_keys(rows, lambda row: (row["respondent_id"].strip(),))

    def validate(row: Mapping[str, str]) -> tuple[dict[str, Scalar], list[str]]:
        reasons: list[str] = []
        respondent_id = text_value(row, "respondent_id", reasons)
        age = integer_value(
            row,
            "age_years",
            reasons,
            minimum=0,
            maximum=85,
            additional_missing=frozenset({"7777", "9999"}),
        )
        sex = text_value(row, "sex", reasons)
        if sex not in {"Female", "Male"}:
            reasons.append("sex:invalid_code")
        race = text_value(row, "race_ethnicity", reasons)
        creatinine = number_value(
            row, "serum_creatinine_mg_dl", reasons, minimum=0.01, maximum=30
        )
        albumin = number_value(row, "urine_albumin_mg_l", reasons, minimum=0, maximum=50000)
        urine_creatinine = number_value(
            row, "urine_creatinine_mg_dl", reasons, minimum=0.01, maximum=5000
        )
        weight = number_value(row, "sample_weight", reasons, minimum=0.000001)
        strata = integer_value(row, "strata", reasons, minimum=1)
        psu = integer_value(row, "psu", reasons, minimum=1)
        cycle = text_value(row, "survey_cycle", reasons)
        if (respondent_id,) in duplicates:
            reasons.append("respondent_id:duplicate_key")
        return {
            "respondent_id": respondent_id,
            "age_years": age,
            "sex": sex,
            "race_ethnicity": race,
            "serum_creatinine_mg_dl": creatinine,
            "urine_albumin_mg_l": albumin,
            "urine_creatinine_mg_dl": urine_creatinine,
            "sample_weight": weight,
            "strata": strata,
            "psu": psu,
            "survey_cycle": cycle,
            "evidence_type": registry.evidence_type,
        }, reasons

    valid, quarantine = validate_rows(rows, validate)
    return result_with_manifest(
        registry=registry,
        snapshot=snapshot,
        valid=valid,
        quarantine=quarantine,
        coverage_values=(str(row["survey_cycle"]) for row in valid),
    )
