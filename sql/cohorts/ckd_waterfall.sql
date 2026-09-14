-- Cross-sectional CKD indicator waterfall for normalized NHANES participants.
-- This is not a confirmed chronic diagnosis: NHANES does not establish persistence
-- for at least three months. Units are creatinine mg/dL, urine albumin mg/L, UACR
-- mg/g, and eGFR mL/min/1.73 m2. Official NHANES URDACT is preferred for
-- UACR. Missing defining labs are excluded, never zeroed. RIDEXPRG code 1 is
-- excluded; codes 2/3 and missing/not-applicable values remain in the domain.
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
            WHEN uacr_mg_g >= 0 THEN uacr_mg_g
            WHEN urine_albumin_mg_l >= 0 AND urine_creatinine_mg_dl > 0
            THEN 100.0 * urine_albumin_mg_l / urine_creatinine_mg_dl
        END AS analysis_uacr_mg_g,
        CASE
            WHEN uacr_mg_g IS NOT NULL THEN uacr_mg_g >= 30.0
            WHEN urine_albumin_mg_l >= 0 AND urine_creatinine_mg_dl > 0 THEN
                100.0 * urine_albumin_mg_l > 30.0 * urine_creatinine_mg_dl
                OR abs(
                    100.0 * urine_albumin_mg_l - 30.0 * urine_creatinine_mg_dl
                ) <= 1e-12 * greatest(
                    abs(100.0 * urine_albumin_mg_l),
                    abs(30.0 * urine_creatinine_mg_dl),
                    1.0
                )
        END AS has_albuminuria
    FROM nhanes_participants
),
eligibility AS (
    SELECT
        *,
        mec_exam_status = 2
            AND sample_weight > 1e-12
            AND strata IS NOT NULL
            AND psu IS NOT NULL AS is_mec_examined_with_valid_design,
        mec_exam_status = 2
            AND sample_weight > 1e-12
            AND strata IS NOT NULL
            AND psu IS NOT NULL
            AND age_years >= 18 AS is_adult,
        mec_exam_status = 2
            AND sample_weight > 1e-12
            AND strata IS NOT NULL
            AND psu IS NOT NULL
            AND age_years >= 18
            AND (pregnancy_status_code IS NULL OR pregnancy_status_code <> 1)
            AS is_adult_excluding_known_pregnancy,
        mec_exam_status = 2
            AND sample_weight > 1e-12
            AND strata IS NOT NULL
            AND psu IS NOT NULL
            AND age_years >= 18
            AND (pregnancy_status_code IS NULL OR pregnancy_status_code <> 1)
            AND egfr_ckd_epi_2021 IS NOT NULL
            AND analysis_uacr_mg_g IS NOT NULL AS has_complete_primary_definition
    FROM derived
),
stages AS (
    SELECT 1 AS stage_order, 'NHANES 2017-2018 participants' AS stage, count(*) AS people
    FROM eligibility
    UNION ALL
    SELECT 2, 'MEC examined with valid design and positive weight',
        count(*) FILTER (WHERE is_mec_examined_with_valid_design)
    FROM eligibility
    UNION ALL
    SELECT 3, 'adults age 18+', count(*) FILTER (WHERE is_adult)
    FROM eligibility
    UNION ALL
    SELECT 4, 'adults excluding known pregnancy',
        count(*) FILTER (WHERE is_adult_excluding_known_pregnancy)
    FROM eligibility
    UNION ALL
    SELECT 5, 'complete eGFR and UACR defining labs',
        count(*) FILTER (WHERE has_complete_primary_definition)
    FROM eligibility
    UNION ALL
    SELECT 6, 'cross-sectional CKD indicator positive',
        count(*) FILTER (
            WHERE has_complete_primary_definition
                AND (egfr_ckd_epi_2021 < 60.0 OR has_albuminuria)
        )
    FROM eligibility
)
SELECT stage_order, stage, people
FROM stages
ORDER BY stage_order;
