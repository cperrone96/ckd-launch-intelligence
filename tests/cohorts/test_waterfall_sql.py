from __future__ import annotations

from pathlib import Path

import duckdb


def test_ckd_waterfall_executes_and_exposes_each_denominator() -> None:
    connection = duckdb.connect()
    connection.execute(
        """
        CREATE TABLE nhanes_participants AS
        SELECT * FROM (VALUES
          (1, 17, 'Male',   2.0, 100.0, 100.0, 1.0, 1, 1),
          (2, 75, 'Female', 1.8,   5.0, 100.0, 1.0, 1, 1),
          (3, 40, 'Male',   0.8,  45.0, 100.0, 1.0, 1, 2),
          (4, 50, 'Female', 0.7,   NULL, NULL, 1.0, 2, 1),
          (5, 50, 'Male',   0.9,  10.0, 100.0, 0.0, 2, 2)
        ) AS t(
          respondent_id, age_years, sex, serum_creatinine_mg_dl,
          urine_albumin_mg_l, urine_creatinine_mg_dl,
          sample_weight, strata, psu
        )
        """
    )
    sql = Path("sql/cohorts/ckd_waterfall.sql").read_text(encoding="utf-8")

    rows = connection.execute(sql).fetchall()

    assert rows == [
        (1, "source records", 5),
        (2, "adults age 18+", 4),
        (3, "valid survey design and positive weight", 3),
        (4, "complete eGFR and UACR defining labs", 2),
        (5, "cross-sectional CKD indicator positive", 2),
    ]
