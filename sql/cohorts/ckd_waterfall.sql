-- Cross-sectional CKD indicator waterfall for normalized NHANES participants.
-- This is not a confirmed chronic diagnosis: NHANES does not establish persistence
-- for at least three months. Units are creatinine mg/dL, urine albumin mg/L, UACR
-- mg/g, and eGFR mL/min/1.73 m2. Missing defining labs are excluded, never zeroed.
WITH derived AS (
    SELECT
        *,
        CASE
            WHEN age_years >= 18
                AND serum_creatinine_mg_dl > 0
                AND lower(sex) IN ('female', 'male')
            THEN
                142.0
                * power(
                    least(
                        serum_creatinine_mg_dl
                            / CASE WHEN lower(sex) = 'female' THEN 0.7 ELSE 0.9 END,
                        1.0
                    ),
                    CASE WHEN lower(sex) = 'female' THEN -0.241 ELSE -0.302 END
                )
                * power(
                    greatest(
                        serum_creatinine_mg_dl
                            / CASE WHEN lower(sex) = 'female' THEN 0.7 ELSE 0.9 END,
                        1.0
                    ),
                    -1.2
                )
                * power(0.9938, age_years)
                * CASE WHEN lower(sex) = 'female' THEN 1.012 ELSE 1.0 END
        END AS egfr_ckd_epi_2021,
        CASE
            WHEN urine_albumin_mg_l >= 0 AND urine_creatinine_mg_dl > 0
            THEN 100.0 * urine_albumin_mg_l / urine_creatinine_mg_dl
        END AS uacr_mg_g
    FROM nhanes_participants
),
eligibility AS (
    SELECT
        *,
        age_years >= 18 AS is_adult,
        age_years >= 18
            AND sample_weight > 0
            AND strata IS NOT NULL
            AND psu IS NOT NULL AS has_valid_design,
        age_years >= 18
            AND sample_weight > 0
            AND strata IS NOT NULL
            AND psu IS NOT NULL
            AND egfr_ckd_epi_2021 IS NOT NULL
            AND uacr_mg_g IS NOT NULL AS has_complete_primary_definition
    FROM derived
),
stages AS (
    SELECT 1 AS stage_order, 'source records' AS stage, count(*) AS people
    FROM eligibility
    UNION ALL
    SELECT 2, 'adults age 18+', count(*) FILTER (WHERE is_adult)
    FROM eligibility
    UNION ALL
    SELECT 3, 'valid survey design and positive weight', count(*) FILTER (WHERE has_valid_design)
    FROM eligibility
    UNION ALL
    SELECT 4, 'complete eGFR and UACR defining labs',
        count(*) FILTER (WHERE has_complete_primary_definition)
    FROM eligibility
    UNION ALL
    SELECT 5, 'cross-sectional CKD indicator positive',
        count(*) FILTER (
            WHERE has_complete_primary_definition
                AND (egfr_ckd_epi_2021 < 60.0 OR uacr_mg_g >= 30.0)
        )
    FROM eligibility
)
SELECT stage_order, stage, people
FROM stages
ORDER BY stage_order;
