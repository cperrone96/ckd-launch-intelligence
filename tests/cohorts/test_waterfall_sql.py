from __future__ import annotations

from pathlib import Path

import duckdb


def test_ckd_waterfall_executes_and_exposes_each_denominator() -> None:
    connection = duckdb.connect()
    connection.execute(
        """
        CREATE TABLE nhanes_participants AS
        SELECT * FROM (VALUES
          (1, 2, 17, 'Male',   NULL, 2.0, 100.0, 100.0, 100.0, 1.0, 1, 1),
          (2, 2, 75, 'Female', 2,    1.8,   5.0, 100.0,   5.0, 1.0, 1, 1),
          (3, 2, 40, 'Male',   NULL, 0.8,  10.2,  34.0,  30.0, 1.0, 1, 2),
          (4, 2, 50, 'Female', 3,    0.7,   NULL, NULL,   NULL, 1.0, 2, 1),
          (5, 1, 50, 'Male',   NULL, 0.9,  10.0, 100.0,  10.0, 5.397605e-79, 2, 2),
          (6, 2, 30, 'Female', 1,    1.8, 100.0, 100.0, 100.0, 1.0, 2, 2)
        ) AS t(
          respondent_id, mec_exam_status, age_years, sex, pregnancy_status_code,
          serum_creatinine_mg_dl, urine_albumin_mg_l, urine_creatinine_mg_dl, uacr_mg_g,
          sample_weight, strata, psu
        )
        """
    )
    sql = Path("sql/cohorts/ckd_waterfall.sql").read_text(encoding="utf-8")

    rows = connection.execute(sql).fetchall()

    assert rows == [
        (1, "NHANES 2017-2018 participants", 6),
        (2, "MEC examined with valid design and positive weight", 5),
        (3, "adults age 18+", 4),
        (4, "adults excluding known pregnancy", 3),
        (5, "complete eGFR and UACR defining labs", 2),
        (6, "cross-sectional CKD indicator positive", 2),
    ]
