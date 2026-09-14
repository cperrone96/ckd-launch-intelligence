"""NHANES participant-level public-use ingestion adapter."""

from __future__ import annotations

import zipfile
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
MAX_SOURCE_BYTES = 300 * 1024 * 1024
RACE_CODES = {
    "Mexican American",
    "Other Hispanic",
    "Non-Hispanic White",
    "Non-Hispanic Black",
    "Non-Hispanic Asian",
    "Other Race - Including Multi-Racial",
}
NATIVE_REQUIRED = {
    "SEQN",
    "RIDAGEYR",
    "RIAGENDR",
    "RIDRETH3",
    "LBXSCR",
    "URXUMA",
    "URXUCR",
    "WTMEC2YR",
    "SDMVSTRA",
    "SDMVPSU",
}
NATIVE_SEX = {"1": "Male", "2": "Female"}
NATIVE_RACE = {
    "1": "Mexican American",
    "2": "Other Hispanic",
    "3": "Non-Hispanic White",
    "4": "Non-Hispanic Black",
    "6": "Non-Hispanic Asian",
    "7": "Other Race - Including Multi-Racial",
}


def _pandas() -> Any:
    try:
        return import_module("pandas")
    except ImportError as exc:
        raise RuntimeError("NHANES XPT ingestion requires the pandas runtime dependency") from exc


def _frame_rows(frame: Any) -> list[dict[str, str]]:
    columns = set(frame.columns)
    missing = sorted(NATIVE_REQUIRED - columns)
    if missing:
        raise ValueError(f"Missing required native NHANES columns: {', '.join(missing)}")
    rows: list[dict[str, str]] = []
    for native in frame.to_dict(orient="records"):
        sex_code = native_scalar_text(native["RIAGENDR"])
        race_code = native_scalar_text(native["RIDRETH3"])
        rows.append(
            {
                "source_release": "2017-2018",
                "respondent_id": native_scalar_text(native["SEQN"]),
                "age_years": native_scalar_text(native["RIDAGEYR"]),
                "sex": NATIVE_SEX.get(sex_code, sex_code),
                "race_ethnicity": NATIVE_RACE.get(race_code, race_code),
                "serum_creatinine_mg_dl": native_scalar_text(native["LBXSCR"]),
                "urine_albumin_mg_l": native_scalar_text(native["URXUMA"]),
                "urine_creatinine_mg_dl": native_scalar_text(native["URXUCR"]),
                "sample_weight": native_scalar_text(native["WTMEC2YR"]),
                "strata": native_scalar_text(native["SDMVSTRA"]),
                "psu": native_scalar_text(native["SDMVPSU"]),
                "survey_cycle": "2017-2018",
            }
        )
    return rows


def _xpt_rows(payload: bytes) -> list[dict[str, str]]:
    """Read a documented, participant-level joined NHANES XPT export."""

    frame = _pandas().read_sas(BytesIO(payload), format="xport")
    return _frame_rows(frame)


def _xpt_bundle_rows(payload: bytes) -> list[dict[str, str]]:
    """Join native DEMO_J, BIOPRO_J, and ALB_CR_J files on participant SEQN."""

    pandas = _pandas()
    expected = {"DEMO_J.XPT", "BIOPRO_J.XPT", "ALB_CR_J.XPT"}
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            by_basename = {Path(info.filename).name.upper(): info for info in archive.infolist()}
            missing = sorted(expected - by_basename.keys())
            if missing:
                raise ValueError(f"Missing required NHANES XPT members: {', '.join(missing)}")
            if sum(by_basename[name].file_size for name in expected) > 750 * 1024 * 1024:
                raise ValueError("NHANES XPT members exceed the 750 MiB expanded limit")
            frames = [
                pandas.read_sas(BytesIO(archive.read(by_basename[name])), format="xport")
                for name in sorted(expected)
            ]
    except zipfile.BadZipFile as exc:
        raise ValueError("NHANES source must be a valid ZIP archive") from exc
    frame = frames[0]
    for component in frames[1:]:
        frame = frame.merge(component, on="SEQN", how="outer", validate="one_to_one")
    return _frame_rows(frame)


def ingest_nhanes(
    source_path_or_url: str | Path, *, cache_dir: Path | None = Path("data/raw")
) -> IngestionResult:
    """Ingest a supported NHANES extract while retaining survey design fields."""

    registry = source_record("nhanes")
    snapshot = load_source(
        source_path_or_url,
        registry=registry,
        cache_dir=cache_dir,
        max_bytes=MAX_SOURCE_BYTES,
    )
    if snapshot.suffix in {".xpt", ".zip"}:
        if not any(token in snapshot.source_uri.lower() for token in {"2017_2018", "2017-2018"}):
            raise ValueError("Native NHANES source locator must identify cycle 2017-2018")
        rows = (
            _xpt_bundle_rows(snapshot.payload)
            if snapshot.suffix == ".zip"
            else _xpt_rows(snapshot.payload)
        )
    else:
        rows = parse_csv(snapshot.payload, REQUIRED)
    require_release_identity(rows, "source_release", registry.version)
    require_release_identity(rows, "survey_cycle", registry.version)
    duplicates = duplicate_keys(rows, lambda row: (row["respondent_id"].strip(),))

    def validate(row: Mapping[str, str]) -> tuple[dict[str, Scalar], list[str]]:
        reasons: list[str] = []
        release = text_value(row, "source_release", reasons)
        if release != registry.version:
            reasons.append("source_release:mismatch")
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
        if race not in RACE_CODES:
            reasons.append("race_ethnicity:invalid_code")
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
        if cycle != registry.version:
            reasons.append("survey_cycle:outside_release")
        if (respondent_id,) in duplicates:
            reasons.append("respondent_id:duplicate_key")
        return {
            "source_release": release,
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
