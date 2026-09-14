-- CMS Medicare Part D provider/drug aggregate mart.
-- Grain: one provider NPI, provider geography, generic drug, and release year.
-- No beneficiary or person identifier is selected or inferred.
CREATE OR REPLACE VIEW analytics_observed.mart_partd_prescribing AS
SELECT
    'partd' AS source,
    source_release,
    year,
    provider_npi,
    provider_state,
    generic_name,
    MIN(drug_name) AS example_brand_name,
    SUM(total_claim_count) AS total_claim_count,
    SUM(total_30_day_fill_count) AS total_30_day_fill_count,
    SUM(total_drug_cost_usd) AS total_drug_cost_usd,
    CASE
        WHEN SUM(total_30_day_fill_count) > 0
        THEN SUM(total_drug_cost_usd) / SUM(total_30_day_fill_count)
        ELSE NULL
    END AS cost_per_30_day_fill_usd,
    CASE
        WHEN LOWER(TRIM(generic_name)) IN ('dapagliflozin', 'empagliflozin', 'finerenone')
        THEN TRUE
        ELSE FALSE
    END AS is_ckd_relevant_therapy_proxy,
    'Medicare Part D prescriptions represented in CMS aggregate public-use data' AS source_population,
    'provider NPI, provider state, generic drug, and year aggregate' AS source_grain,
    MAX(evidence_type) AS evidence_type,
    DATE '2026-09-11' AS registry_as_of_date,
    'Therapy proxy is drug-name based and not an indication; aggregate records do not '
        || 'support beneficiary utilization, adherence, outcomes, or patient linkage.' AS limitation
FROM raw_partd.records
GROUP BY source_release, year, provider_npi, provider_state, generic_name;
