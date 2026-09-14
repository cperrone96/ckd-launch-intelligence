-- ClinicalTrials.gov source-specific registered-study landscape marts.
-- A row represents a registry study. Enrollment is the submitted study-level
-- target, not observed enrollment or a patient-level outcome.
-- Evidence and source-manifest fields are grouping keys; mixed source provenance is
-- intentionally segregated rather than collapsed.

CREATE OR REPLACE VIEW analytics_observed.mart_trial_status AS
SELECT
    'clinicaltrials' AS source,
    overall_status,
    COUNT(*) AS study_count,
    CASE WHEN COUNT(enrollment) > 0 THEN SUM(enrollment) ELSE NULL END
        AS total_reported_enrollment,
    SUM(CASE WHEN enrollment IS NOT NULL THEN 1 ELSE 0 END)
        AS studies_with_reported_enrollment,
    MAX(last_update_date) AS latest_study_update_date,
    source_retrieved_at,
    source_manifest_checksum,
    evidence_type,
    'registered study grouped by recruitment status' AS source_grain,
    'Registry status is submitted study metadata, not an active-site or outcome measure.'
        AS limitation
FROM raw_trials.studies
GROUP BY overall_status, evidence_type, source_retrieved_at, source_manifest_checksum;

CREATE OR REPLACE VIEW analytics_observed.mart_trial_composition AS
SELECT
    'clinicaltrials' AS source,
    study_type,
    phase,
    COUNT(*) AS study_count,
    CASE WHEN COUNT(enrollment) > 0 THEN SUM(enrollment) ELSE NULL END
        AS total_reported_enrollment,
    SUM(CASE WHEN enrollment IS NOT NULL THEN 1 ELSE 0 END)
        AS studies_with_reported_enrollment,
    MAX(last_update_date) AS latest_study_update_date,
    source_retrieved_at,
    source_manifest_checksum,
    evidence_type,
    'registered study grouped by study type and submitted phase' AS source_grain,
    'Phase and enrollment are registry fields and do not establish efficacy or market share.'
        AS limitation
FROM raw_trials.studies
GROUP BY study_type, phase, evidence_type, source_retrieved_at, source_manifest_checksum;

CREATE OR REPLACE VIEW analytics_observed.mart_trial_sponsors AS
SELECT
    'clinicaltrials' AS source,
    sponsor,
    COUNT(*) AS study_count,
    MAX(last_update_date) AS latest_study_update_date,
    source_retrieved_at,
    source_manifest_checksum,
    evidence_type,
    'registered study grouped by submitted lead sponsor' AS source_grain,
    'Sponsor counts describe registry records and are not investment, trial success, or access claims.'
        AS limitation
FROM raw_trials.studies
GROUP BY sponsor, evidence_type, source_retrieved_at, source_manifest_checksum;
