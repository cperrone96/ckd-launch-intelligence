"""Extra NHANES 2017-2018 predictors for the patient-finding ablation analysis.

Five more public-use files (``data/manifests/nhanes-2017-2018-predictor-ablation.json``)
plus extra columns from three files the base loader already verifies. Coding follows
the base loader: refused (7/77) or don't-know (9/99) answers to clinical questions stay
missing and are never recoded to "No". Income nonresponse is common (about one in
eight) and informative, so it becomes its own ``"Not reported"`` level. The medical
history and education questions are asked only of adults 20 and older, so younger
adults leave the ablation cohort.

Prescription reason codes (``RXDRSC1``-``RXDRSC3``) are never read: some name a kidney
diagnosis. The drug name is the only medication input.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ckd_intelligence.cohorts.nhanes_2017_2018 import RAW_DIRECTORY
from ckd_intelligence.modeling.patient_finding import (
    POINT_OF_CARE_LAB_FEATURES,
    QUESTIONNAIRE_ABLATION_FEATURES,
    LeakageError,
)

ABLATION_MANIFEST_PATH = Path("data/manifests/nhanes-2017-2018-predictor-ablation.json")

# Columns read from each file (SEQN is the join key in every file). DEMO_J, BMX_J and
# BPX_J are verified by the base manifest; the other five by the ablation manifest.
ABLATION_COMPONENT_COLUMNS: dict[str, tuple[str, ...]] = {
    "DEMO_J.xpt": ("INDFMPIR", "DMDEDUC2"),
    "BMX_J.xpt": ("BMXWAIST",),
    "BPX_J.xpt": ("BPXDI1", "BPXDI2", "BPXDI3", "BPXDI4"),
    "GHB_J.xpt": ("LBXGH",),
    "CBC_J.xpt": ("LBXHGB",),
    "MCQ_J.xpt": ("MCQ160B", "MCQ160C", "MCQ160E", "MCQ160F", "MCQ160N", "MCQ053"),
    "HUQ_J.xpt": ("HUQ010", "HUQ051", "HUQ071"),
    "RXQ_RX_J.xpt": ("RXDUSE", "RXDDRUG"),
}

MEDICATION_CLASS_PATTERNS: dict[str, str] = {
    "medication_ace_or_arb": r"PRIL\b|SARTAN\b",
    "medication_diuretic": (
        r"HYDROCHLOROTHIAZIDE|CHLORTHALIDONE|FUROSEMIDE|TORSEMIDE|BUMETANIDE|"
        r"SPIRONOLACTONE|TRIAMTERENE|INDAPAMIDE|METOLAZONE|EPLERENONE"
    ),
    "medication_insulin": r"INSULIN",
    # VASTATIN, not STATIN: nystatin is an antifungal.
    "medication_statin": r"VASTATIN\b",
    "medication_nsaid": (
        r"IBUPROFEN|NAPROXEN|MELOXICAM|DICLOFENAC|CELECOXIB|INDOMETHACIN|ETODOLAC|NABUMETONE"
    ),
    "medication_other_antihypertensive": (
        r"AMLODIPINE|NIFEDIPINE|DILTIAZEM|VERAPAMIL|OLOL\b|ALOL\b|ILOL\b|CLONIDINE|HYDRALAZINE|"
        r"DOXAZOSIN|TERAZOSIN"
    ),
}
# Eye drops and skin products don't count toward systemic classes (timolol eye drops
# are not a blood-pressure pill), though they still count as prescriptions taken.
NON_SYSTEMIC_PATTERN = r"OPHTHALMIC|TOPICAL"
_YES_NO = {1.0: "Yes", 2.0: "No"}
_HEALTH = {1.0: "Excellent", 2.0: "Very good", 3.0: "Good", 4.0: "Fair", 5.0: "Poor"}
_VISITS = {0.0: "0", 1.0: "1", 2.0: "2-5", 3.0: "2-5", 4.0: "6-9", 5.0: "6-9"}
_VISITS.update({code: "10+" for code in (6.0, 7.0, 8.0)})
_EDUCATION = {
    1.0: "<9th grade",
    2.0: "9-11th grade",
    3.0: "High school",
    4.0: "Some college",
    5.0: "College graduate",
}
NOT_REPORTED = "Not reported"


def yes_no(answers: pd.Series) -> pd.Series:
    """1 -> Yes, 2 -> No; refused, don't know and blank stay missing."""

    return answers.map(_YES_NO).astype("string")


def self_rated_health(answers: pd.Series) -> pd.Series:
    """HUQ010 general health, Excellent to Poor; 7/9 stay missing."""

    return answers.map(_HEALTH).astype("string")


def care_visits_band(codes: pd.Series) -> pd.Series:
    """HUQ051 health-care visits in the past year, grouped; 77/99 stay missing."""

    return codes.map(_VISITS).astype("string")


def income_poverty_band(ratio: pd.Series) -> pd.Series:
    """Family income-to-poverty ratio in four bands; nonresponse is its own level."""

    banded = pd.cut(ratio, [-np.inf, 1.0, 2.0, 4.0, np.inf], right=False,
                    labels=["<1", "1-2", "2-4", "4+"])  # fmt: skip
    return banded.astype("string").fillna(NOT_REPORTED)


def education_level(codes: pd.Series) -> pd.Series:
    """DMDEDUC2 (asked of adults 20+); refused, don't know and not asked stay missing."""

    return codes.map(_EDUCATION).astype("string")


def mean_positive_readings(readings: pd.DataFrame) -> pd.Series:
    """Mean of the readings above zero; NHANES records an inaudible diastolic as 0."""

    # SAS XPORT encodes 0 as ~5.4e-79, so compare against a small tolerance, not 0.
    return readings.where(readings > 1e-12).mean(axis=1, skipna=True)


def medication_features(rx: pd.DataFrame) -> pd.DataFrame:
    """Per-person medication class flags and a prescription-count band.

    Takes only ``SEQN``, ``RXDUSE`` and ``RXDDRUG``. Any reason-code column fails
    closed. ``RXDUSE`` 2 (no prescription in the past 30 days) gives "No" flags and a
    count of "0"; refused or don't know leaves every medication field missing.
    """

    reason_columns = sorted(column for column in rx.columns if column.startswith("RXDRSC"))
    if reason_columns:
        raise LeakageError(
            f"prescription reason codes are not permitted: {', '.join(reason_columns)}"
        )
    use = rx.groupby("SEQN")["RXDUSE"].first()
    taking = rx.loc[rx["RXDUSE"].eq(1.0)].copy()
    taking["drug"] = taking["RXDDRUG"].fillna("").astype(str).str.upper()
    out = pd.DataFrame(index=use.index)
    answered = use.isin([1.0, 2.0])
    systemic = taking.loc[~taking["drug"].str.contains(NON_SYSTEMIC_PATTERN, regex=True)]
    for name, pattern in MEDICATION_CLASS_PATTERNS.items():
        users = set(systemic.loc[systemic["drug"].str.contains(pattern, regex=True), "SEQN"])
        flags = pd.Series(np.where(out.index.isin(users), "Yes", "No"), index=out.index)
        out[name] = flags.where(answered).astype("string")
    count = taking.groupby("SEQN").size().reindex(out.index, fill_value=0)
    band = pd.cut(count, [-1, 0, 2, 4, np.inf], labels=["0", "1-2", "3-4", "5+"])
    out["prescription_count_band"] = band.astype("string").where(answered)
    return out.reset_index()


def normalize_sas_zero(frame: pd.DataFrame) -> pd.DataFrame:
    """Replace the SAS XPORT pseudo-zero (about 5.4e-79) with a true 0 in numeric columns.

    Without this, code 0 answers (such as "no health-care visits") miss their mapping
    and become missing.
    """

    out = frame.copy()
    numeric = out.select_dtypes(include="number").columns
    out[numeric] = out[numeric].mask(out[numeric].abs() < 1e-12, 0.0)
    return out


def _read(raw_dir: Path, name: str) -> pd.DataFrame:
    frame = pd.read_sas(raw_dir / name, format="xport", encoding="latin1")
    # Select immediately so no unlisted column (such as RXDRSC*) travels further.
    return normalize_sas_zero(frame.loc[:, ["SEQN", *ABLATION_COMPONENT_COLUMNS[name]]])


def load_ablation_predictors(root: Path) -> pd.DataFrame:
    """One row per NHANES participant: ``respondent_id`` plus the 22 ablation predictors."""

    raw_dir = root / RAW_DIRECTORY
    people = _read(raw_dir, "DEMO_J.xpt")
    for name in ABLATION_COMPONENT_COLUMNS:
        if name in {"DEMO_J.xpt", "RXQ_RX_J.xpt"}:
            continue
        people = people.merge(_read(raw_dir, name), on="SEQN", how="left", validate="one_to_one")
    medications = medication_features(_read(raw_dir, "RXQ_RX_J.xpt"))
    people = people.merge(medications, on="SEQN", how="left", validate="one_to_one")
    history = {
        "heart_failure_history": "MCQ160B",
        "coronary_disease_history": "MCQ160C",
        "heart_attack_history": "MCQ160E",
        "stroke_history": "MCQ160F",
        "gout_history": "MCQ160N",
        "anemia_treatment": "MCQ053",
    }
    derived = pd.DataFrame(
        {
            "respondent_id": people["SEQN"],
            "hba1c_percent": people["LBXGH"],
            "hemoglobin_g_dl": people["LBXHGB"],
            "waist_cm": people["BMXWAIST"],
            "diastolic_blood_pressure": mean_positive_readings(
                people[["BPXDI1", "BPXDI2", "BPXDI3", "BPXDI4"]]
            ),
            **{name: yes_no(people[code]) for name, code in history.items()},
            **{name: people[name] for name in MEDICATION_CLASS_PATTERNS},
            "prescription_count_band": people["prescription_count_band"],
            "income_poverty_band": income_poverty_band(people["INDFMPIR"]),
            "education_level": education_level(people["DMDEDUC2"]),
            "self_rated_health": self_rated_health(people["HUQ010"]),
            "hospitalized_past_year": yes_no(people["HUQ071"]),
            "care_visits_band": care_visits_band(people["HUQ051"]),
        }
    )
    return derived.loc[
        :, ["respondent_id", *POINT_OF_CARE_LAB_FEATURES, *QUESTIONNAIRE_ABLATION_FEATURES]
    ]
