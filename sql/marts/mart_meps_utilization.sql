-- MEPS HC-243 2022 source-specific person-year mart.
-- DSKIDN53 is a documented diabetes-related kidney-problem proxy, not confirmed CKD.
-- Grain: year x proxy status. Counts and weighted quantities are never event-person
-- estimates and no record is linked to another source family.
CREATE OR REPLACE VIEW analytics_observed.mart_meps_utilization AS
WITH classified AS (
    SELECT
        *,
        CASE
            WHEN dcs_eligible = 1 AND diabetes_reported = 1 AND kidney_problem_proxy = 1
                THEN 'proxy_positive'
            WHEN dcs_eligible = 1 AND diabetes_reported = 1 AND kidney_problem_proxy = 2
                THEN 'proxy_negative'
            WHEN dcs_eligible = 1 AND diabetes_reported = 1
                THEN 'proxy_unknown'
            ELSE 'outside_proxy_domain'
        END AS kidney_proxy_status,
        person_weight > 0 AND variance_stratum IS NOT NULL AND variance_psu IS NOT NULL
            AS design_eligible
    FROM raw_meps.people
)
SELECT
    'meps' AS source,
    source_release,
    year,
    kidney_proxy_status,
    COUNT(*) AS source_record_count,
    SUM(CASE WHEN design_eligible THEN 1 ELSE 0 END) AS design_eligible_record_count,
    SUM(CASE WHEN kidney_proxy_status IN ('proxy_positive', 'proxy_negative') THEN 1 ELSE 0 END)
        AS complete_proxy_record_count,
    SUM(CASE WHEN kidney_proxy_status IN ('proxy_positive', 'proxy_negative')
        THEN proxy_weight ELSE 0 END) AS weighted_population,
    SUM(CASE WHEN kidney_proxy_status IN ('proxy_positive', 'proxy_negative')
        THEN office_visits * proxy_weight ELSE 0 END) AS weighted_office_visits,
    SUM(CASE WHEN kidney_proxy_status IN ('proxy_positive', 'proxy_negative')
        THEN outpatient_visits * proxy_weight ELSE 0 END) AS weighted_outpatient_visits,
    SUM(CASE WHEN kidney_proxy_status IN ('proxy_positive', 'proxy_negative')
        THEN emergency_visits * proxy_weight ELSE 0 END) AS weighted_emergency_visits,
    SUM(CASE WHEN kidney_proxy_status IN ('proxy_positive', 'proxy_negative')
        THEN inpatient_stays * proxy_weight ELSE 0 END) AS weighted_inpatient_stays,
    SUM(CASE WHEN kidney_proxy_status IN ('proxy_positive', 'proxy_negative')
        THEN prescription_medicines * proxy_weight ELSE 0 END) AS weighted_prescription_medicines,
    SUM(CASE WHEN kidney_proxy_status IN ('proxy_positive', 'proxy_negative')
        THEN total_expenditure_usd * proxy_weight ELSE 0 END) AS weighted_expenditure_usd,
    MAX(source_retrieved_at) AS source_retrieved_at,
    MAX(source_manifest_checksum) AS source_manifest_checksum,
    MAX(evidence_type) AS evidence_type,
    'U.S. civilian, noninstitutionalized population represented by MEPS HC-243 2022; '
        || 'proxy analysis is restricted to DCS-eligible respondents with reported diabetes.'
        AS source_population,
    'HC-243 person-year consolidated record grouped by year and DSKIDN53 proxy status'
        AS source_grain,
    'Use DIABW22F for proxy-domain population estimates and VARSTR/VARPSU for variance. '
        || 'DSKIDN53 reflects diabetes-related kidney problems, not a CKD diagnosis.' AS limitation
FROM classified
GROUP BY source_release, year, kidney_proxy_status;
