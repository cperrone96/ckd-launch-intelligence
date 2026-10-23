"""Build the NHANES 2017-2018 analysis frame from checksum-verified public-use files.

The CDC/NCHS XPT files listed in ``data/manifests/nhanes-2017-2018-patient-need.json``
are joined one-to-one on ``SEQN`` (within one survey cycle; no cross-source linkage).
The returned frame keeps every MEC-examined participant with a positive exam weight
and a valid design, so survey estimates can treat adults as a domain of the full
design. Missing laboratory or questionnaire values stay missing; they are never
recoded to zero or "No".
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ckd_intelligence.cohorts.definitions import CKDDefinition, classify_ckd

MANIFEST_PATH = Path("data/manifests/nhanes-2017-2018-patient-need.json")
RAW_DIRECTORY = Path("data/raw/nhanes/2017-2018")

RACE_ETHNICITY = {
    1.0: "Mexican American",
    2.0: "Other Hispanic",
    3.0: "Non-Hispanic White",
    4.0: "Non-Hispanic Black",
    6.0: "Non-Hispanic Asian",
    7.0: "Other Race - Including Multi-Racial",
}
SEX = {1.0: "Male", 2.0: "Female"}
# DIQ010 "Doctor told you have diabetes": 7 (refused) and 9 (don't know) stay missing.
DIABETES = {1.0: "Yes", 2.0: "No", 3.0: "Borderline"}
# BPQ020 "Ever told you had high blood pressure".
HYPERTENSION = {1.0: "Yes", 2.0: "No"}

# Columns read from each component file (SEQN is the join key in every file).
COMPONENT_COLUMNS: dict[str, tuple[str, ...]] = {
    "DEMO_J.xpt": (
        "RIDSTATR",
        "RIDAGEYR",
        "RIAGENDR",
        "RIDRETH3",
        "RIDEXPRG",
        "WTMEC2YR",
        "SDMVSTRA",
        "SDMVPSU",
    ),
    "BIOPRO_J.xpt": ("LBXSCR",),
    "ALB_CR_J.xpt": ("URXUMA", "URXUCR", "URDACT"),
    "BMX_J.xpt": ("BMXBMI",),
    "BPX_J.xpt": ("BPXSY1", "BPXSY2", "BPXSY3", "BPXSY4"),
    "DIQ_J.xpt": ("DIQ010",),
    "BPQ_J.xpt": ("BPQ020",),
    "SMQ_J.xpt": ("SMQ020", "SMQ040"),
}
DEFINITIONS = (
    CKDDefinition.primary(),
    CKDDefinition.egfr_only(),
    CKDDefinition.albuminuria_only(),
)


class SnapshotError(ValueError):
    """Raised when a local NHANES file does not match the committed manifest."""


@dataclass(frozen=True, slots=True)
class NhanesFrame:
    """MEC-examined participants plus the raw participant count for the waterfall."""

    people: pd.DataFrame
    source_participant_count: int


def load_manifest(root: Path) -> dict[str, Any]:
    """Read the committed NHANES source manifest."""

    payload: dict[str, Any] = json.loads((root / MANIFEST_PATH).read_text(encoding="utf-8"))
    return payload


def snapshot_is_available(root: Path, manifest: Mapping[str, Any]) -> bool:
    """Return True when every manifest file is present and verified.

    Returns False when any file is absent (the notebooks then fall back to the
    committed fixture). Raises ``SnapshotError`` when a file is present but its
    size or SHA-256 differs from the manifest, because silently analysing different
    bytes would break provenance.
    """

    raw_dir = root / RAW_DIRECTORY
    files = list(manifest["files"])
    if not all((raw_dir / str(item["name"])).is_file() for item in files):
        return False
    for item in files:
        path = raw_dir / str(item["name"])
        if path.stat().st_size != item["bytes"]:
            raise SnapshotError(f"unexpected byte count: {item['name']}")
        if sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise SnapshotError(f"checksum mismatch: {item['name']}")
    return True


def _read_component(raw_dir: Path, name: str) -> pd.DataFrame:
    columns = ["SEQN", *COMPONENT_COLUMNS[name]]
    frame = pd.read_sas(raw_dir / name, format="xport")
    return frame.loc[:, columns]


def _smoking_status(ever: pd.Series, now: pd.Series) -> pd.Series:
    """Never (<100 lifetime cigarettes), Former or Current smoker; otherwise missing."""

    status = pd.Series(pd.NA, index=ever.index, dtype="string")
    status[ever.eq(2)] = "Never"
    status[ever.eq(1) & now.isin([1.0, 2.0])] = "Current"
    status[ever.eq(1) & now.eq(3)] = "Former"
    return status


def load_examined_participants(root: Path) -> NhanesFrame:
    """Join the verified XPT files and keep MEC-examined participants with a valid design."""

    raw_dir = root / RAW_DIRECTORY
    joined = _read_component(raw_dir, "DEMO_J.xpt")
    source_participant_count = len(joined)
    for name in COMPONENT_COLUMNS:
        if name == "DEMO_J.xpt":
            continue
        joined = joined.merge(
            _read_component(raw_dir, name), on="SEQN", how="left", validate="one_to_one"
        )
    systolic = joined[["BPXSY1", "BPXSY2", "BPXSY3", "BPXSY4"]]
    people = pd.DataFrame(
        {
            "respondent_id": joined["SEQN"],
            "mec_exam_status": joined["RIDSTATR"],
            "age_years": joined["RIDAGEYR"],
            "sex": joined["RIAGENDR"].map(SEX),
            "race_ethnicity": joined["RIDRETH3"].map(RACE_ETHNICITY),
            "pregnancy_status_code": joined["RIDEXPRG"],
            "serum_creatinine_mg_dl": joined["LBXSCR"],
            "urine_albumin_mg_l": joined["URXUMA"],
            "urine_creatinine_mg_dl": joined["URXUCR"],
            "uacr_mg_g": joined["URDACT"],
            "sample_weight": joined["WTMEC2YR"].where(joined["WTMEC2YR"].gt(1e-12)),
            "strata": joined["SDMVSTRA"],
            "psu": joined["SDMVPSU"],
            "body_mass_index": joined["BMXBMI"],
            # Mean of the available auscultatory readings (up to four).
            "systolic_blood_pressure": systolic.mean(axis=1, skipna=True),
            "diabetes_history": joined["DIQ010"].map(DIABETES).astype("string"),
            "hypertension_history": joined["BPQ020"].map(HYPERTENSION).astype("string"),
            "smoking_status": _smoking_status(joined["SMQ020"], joined["SMQ040"]),
        }
    )
    examined = (
        people["mec_exam_status"].eq(2)
        & people["sample_weight"].notna()
        & people["strata"].notna()
        & people["psu"].notna()
    )
    return NhanesFrame(
        people=people.loc[examined].reset_index(drop=True),
        source_participant_count=source_participant_count,
    )


def add_ckd_indicators(people: pd.DataFrame) -> pd.DataFrame:
    """Add the primary and sensitivity indicators on one common complete-case domain.

    The domain is adults (18+) excluding known pregnancy (RIDEXPRG=1) with both
    defining laboratory measures. Single-marker sensitivity indicators are set to
    missing outside that domain so every definition shares one denominator.
    """

    output = people.copy()
    for definition in DEFINITIONS:
        output[definition.name] = classify_ckd(output, definition)
    complete = eligible_domain(output) & output[CKDDefinition.primary().name].notna()
    for definition in DEFINITIONS:
        output.loc[~complete, definition.name] = pd.NA
    return output


def eligible_domain(people: pd.DataFrame) -> pd.Series:
    """Adults age 18+ excluding known pregnancy; other pregnancy codes stay eligible."""

    adult = pd.to_numeric(people["age_years"], errors="coerce").ge(18)
    pregnancy = pd.to_numeric(people["pregnancy_status_code"], errors="coerce")
    known_pregnant = pregnancy.eq(1).fillna(False)
    return (adult & ~known_pregnant).fillna(False).astype(bool)


def survey_cluster_labels(people: pd.DataFrame) -> pd.Series:
    """Masked variance stratum and PSU as one grouping label for leakage-safe splits."""

    strata = pd.to_numeric(people["strata"]).astype(np.int64).astype(str)
    psu = pd.to_numeric(people["psu"]).astype(np.int64).astype(str)
    return (strata + "-psu-" + psu).rename("survey_cluster")
