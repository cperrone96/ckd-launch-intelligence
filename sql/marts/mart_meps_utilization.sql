-- MEPS source-specific utilization and expenditure mart.
-- Grain: one year, condition code, and event type.
-- The person weight expands the normalized public-use event rows to the MEPS
-- represented population. It does not make an event-level file a patient-journey
-- table, and no record is linked to NHANES, Part D, or ClinicalTrials.gov.
CREATE OR REPLACE VIEW analytics_observed.mart_meps_utilization AS
SELECT
    'meps' AS source,
    source_release,
    year,
    condition_code,
    event_type,
    COUNT(*) AS observed_record_count,
    SUM(person_weight) AS weighted_event_count,
    SUM(expenditure_usd * person_weight) AS weighted_expenditure_usd,
    AVG(expenditure_usd) AS mean_observed_expenditure_usd,
    SUM(CASE WHEN rx_name IS NOT NULL AND TRIM(rx_name) <> '' THEN 1 ELSE 0 END)
        AS records_with_prescription_name,
    'U.S. civilian, noninstitutionalized population represented by MEPS' AS source_population,
    'normalized MEPS public-use event/person-year record grouped by year, condition, event type'
        AS source_grain,
    MAX(evidence_type) AS evidence_type,
    DATE '2026-09-11' AS registry_as_of_date,
    'Survey weights are retained; variance design fields remain in raw_meps.events. '
        || 'This is not provider prescribing or patient-level linkage.' AS limitation
FROM raw_meps.events
GROUP BY source_release, year, condition_code, event_type;
