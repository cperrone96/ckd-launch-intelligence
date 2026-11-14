from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ckd_intelligence.cohorts import nhanes_2017_2018 as nhanes
from ckd_intelligence.cohorts import nhanes_2017_2018_ablation as ablation
from ckd_intelligence.modeling.patient_finding import (
    POINT_OF_CARE_LAB_FEATURES,
    QUESTIONNAIRE_ABLATION_FEATURES,
    LeakageError,
)


def test_medication_features_refuse_reason_codes() -> None:
    rx = pd.DataFrame(
        {"SEQN": [1], "RXDUSE": [1.0], "RXDDRUG": ["LISINOPRIL"], "RXDRSC1": ["N18.3"]}
    )

    with pytest.raises(LeakageError, match="RXDRSC1"):
        ablation.medication_features(rx)


def test_medication_flags_and_count_band() -> None:
    rx = pd.DataFrame(
        {
            "SEQN": [1, 1, 2, 3],
            "RXDUSE": [1.0, 1.0, 2.0, 9.0],
            "RXDDRUG": ["LISINOPRIL", "FUROSEMIDE", "", ""],
        }
    )

    out = ablation.medication_features(rx).set_index("SEQN")

    assert out.loc[1, "medication_ace_or_arb"] == "Yes"
    assert out.loc[1, "medication_diuretic"] == "Yes"
    assert out.loc[1, "medication_statin"] == "No"
    assert out.loc[1, "prescription_count_band"] == "1-2"
    assert out.loc[2, "prescription_count_band"] == "0"
    assert out.loc[2, "medication_statin"] == "No"
    # Refused or don't know on "taken a prescription medicine" stays missing.
    assert out.loc[3].isna().all()


def test_combination_products_set_every_matching_class() -> None:
    rx = pd.DataFrame({"SEQN": [1], "RXDUSE": [1.0], "RXDDRUG": ["LOSARTAN; HYDROCHLOROTHIAZIDE"]})

    out = ablation.medication_features(rx).set_index("SEQN")

    assert out.loc[1, "medication_ace_or_arb"] == "Yes"
    assert out.loc[1, "medication_diuretic"] == "Yes"


def test_refused_and_dont_know_stay_missing() -> None:
    answers = pd.Series([1.0, 2.0, 7.0, 9.0, np.nan])

    coded = ablation.yes_no(answers)

    assert coded.iloc[:2].tolist() == ["Yes", "No"]
    assert coded.iloc[2:].isna().all()
    health = ablation.self_rated_health(pd.Series([1.0, 5.0, 7.0, 9.0]))
    assert health.iloc[:2].tolist() == ["Excellent", "Poor"]
    assert health.iloc[2:].isna().all()


def test_care_visit_codes_map_to_bands() -> None:
    codes = pd.Series([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 77.0, 99.0])

    bands = ablation.care_visits_band(codes)

    assert bands.iloc[:8].tolist() == ["0", "1", "2-5", "2-5", "6-9", "6-9", "10+", "10+"]
    assert bands.iloc[8:].isna().all()


def test_income_nonresponse_is_not_reported() -> None:
    income = ablation.income_poverty_band(pd.Series([0.5, 1.0, 1.5, 3.0, 5.0, np.nan]))

    assert income.tolist() == ["<1", "1-2", "1-2", "2-4", "4+", "Not reported"]


def test_education_nonresponse_stays_missing() -> None:
    # Only a handful of adults refuse; a level that small breaks cross-validation folds.
    education = ablation.education_level(pd.Series([1.0, 5.0, 7.0, 9.0, np.nan]))

    assert education.iloc[:2].tolist() == ["<9th grade", "College graduate"]
    assert education.iloc[2:].isna().all()


def test_diastolic_ignores_zero_readings() -> None:
    readings = pd.DataFrame({"a": [0.0, np.nan], "b": [80.0, 0.0], "c": [82.0, np.nan]})

    assert ablation.mean_positive_readings(readings).iloc[0] == pytest.approx(81.0)
    assert np.isnan(ablation.mean_positive_readings(readings).iloc[1])


def test_ablation_manifest_lists_every_new_file_the_loader_reads() -> None:
    manifest = json.loads(Path(ablation.ABLATION_MANIFEST_PATH).read_text(encoding="utf-8"))
    names = {item["name"] for item in manifest["files"]}

    assert names == set(ablation.ABLATION_COMPONENT_COLUMNS) - set(nhanes.COMPONENT_COLUMNS)
    assert all(item["url"].startswith("https://wwwn.cdc.gov/") for item in manifest["files"])
    read = {
        column for columns in ablation.ABLATION_COMPONENT_COLUMNS.values() for column in columns
    }
    assert not any(column.startswith("RXDRSC") for column in read)


_ROOT = Path(__file__).resolve().parents[2]


def _snapshots_present() -> bool:
    raw = _ROOT / nhanes.RAW_DIRECTORY
    return all((raw / name).is_file() for name in ablation.ABLATION_COMPONENT_COLUMNS)


@pytest.mark.skipif(
    not _snapshots_present(),
    reason="raw NHANES files not downloaded (run scripts/retrieve_surveys.py)",
)
def test_verified_snapshot_has_one_row_per_participant() -> None:
    predictors = ablation.load_ablation_predictors(_ROOT)

    assert predictors["respondent_id"].is_unique
    assert list(predictors.columns) == [
        "respondent_id",
        *POINT_OF_CARE_LAB_FEATURES,
        *QUESTIONNAIRE_ABLATION_FEATURES,
    ]
    assert len(predictors) == 9254
    assert predictors["hba1c_percent"].dropna().between(3.0, 20.0).all()
    # Code 0 ("no visits") survives the SAS pseudo-zero encoding.
    assert (predictors["care_visits_band"] == "0").sum() > 1000


def test_diastolic_treats_sas_pseudo_zero_as_zero() -> None:
    # SAS XPORT stores 0 as 5.397605346934028e-79; it must not count as a reading.
    readings = pd.DataFrame({"a": [5.397605346934028e-79], "b": [70.0], "c": [74.0]})

    assert ablation.mean_positive_readings(readings).iloc[0] == pytest.approx(72.0)


def test_sas_pseudo_zero_codes_become_true_zero() -> None:
    frame = pd.DataFrame({"SEQN": [1.0, 2.0], "HUQ051": [5.397605346934028e-79, 3.0]})

    normalized = ablation.normalize_sas_zero(frame)

    assert normalized["HUQ051"].tolist() == [0.0, 3.0]
    assert ablation.care_visits_band(normalized["HUQ051"]).tolist() == ["0", "2-5"]
