-- CMS DE-SynPUF 2008-2010 method demonstration.
-- This mart is deliberately synthetic-only. It must never be joined to
-- analytics_observed or used to estimate Medicare beneficiaries.

CREATE SCHEMA IF NOT EXISTS analytics_synthetic;
DROP TABLE IF EXISTS analytics_synthetic.mart_journeys;

CREATE TABLE analytics_synthetic.mart_journeys AS
WITH source_rows AS (
    SELECT
        CAST(beneficiary_id AS VARCHAR) AS synthetic_id,
        CAST(claim_id AS VARCHAR) AS claim_id,
        claim_type,
        CAST(service_from_date AS DATE) AS event_date,
        CAST(service_through_date AS DATE) AS event_through_date,
        diagnosis_code,
        'public_synthetic' AS evidence_type
    FROM raw_synpuf.claims
    WHERE source_release = '2008-2010'
), ordered AS (
    SELECT
        source_rows.*,
        ROW_NUMBER() OVER (
            PARTITION BY synthetic_id
            ORDER BY event_date, event_through_date, claim_id
        ) AS event_position,
        CASE WHEN REPLACE(UPPER(diagnosis_code), '.', '') LIKE '585%'
                  OR REPLACE(UPPER(diagnosis_code), '.', '') LIKE '586%'
                  OR REPLACE(UPPER(diagnosis_code), '.', '') LIKE '588%'
             THEN 1 ELSE 0 END AS is_ckd_signal
    FROM source_rows
    WHERE event_date BETWEEN DATE '2008-01-01' AND DATE '2010-12-31'
), indexed AS (
    SELECT
        ordered.*,
        MIN(event_date) OVER (PARTITION BY synthetic_id) AS index_date,
        MIN(CASE WHEN is_ckd_signal = 1 THEN event_date END)
            OVER (PARTITION BY synthetic_id) AS target_date
    FROM ordered
), bounded AS (
    SELECT
        indexed.*,
        LEAST(DATE '2010-12-31', index_date + INTERVAL '365 days') AS follow_up_end
    FROM indexed
), classified AS (
    SELECT
        bounded.*,
        CASE
            WHEN event_position = 1 THEN 'index'
            WHEN is_ckd_signal = 1 AND event_date = target_date THEN 'target'
            WHEN target_date IS NULL OR event_date < target_date THEN 'pre_target'
            ELSE 'follow_up'
        END AS event_kind
    FROM bounded
)
SELECT
    synthetic_id,
    claim_id,
    event_date,
    event_through_date,
    claim_type,
    diagnosis_code,
    event_kind,
    event_position AS event_order,
    is_ckd_signal,
    index_date,
    target_date,
    follow_up_end,
    evidence_type
FROM classified;

-- Contract checks for a compatible DuckDB/PostgreSQL execution harness:
-- * one row per synthetic claim_id;
-- * evidence_type is exactly public_synthetic;
-- * no analytics_observed relation is referenced by this mart;
-- * deterministic order is event_date, event_through_date, claim_id.
