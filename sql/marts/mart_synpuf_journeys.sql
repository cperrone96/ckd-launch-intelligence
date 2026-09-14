-- CMS DE-SynPUF 2008-2010 method demonstration.
-- This mart is deliberately synthetic-only. It must never be joined to
-- analytics_observed or used to estimate Medicare beneficiaries.
-- The caller must run the contract precondition before this script:
--   source_release = '2008-2010' and evidence_type = 'public_synthetic' for
--   every input row, with unique non-null beneficiary_id and claim_id.

CREATE SCHEMA IF NOT EXISTS analytics_synthetic;
DROP TABLE IF EXISTS analytics_synthetic.mart_journeys;
DROP TABLE IF EXISTS analytics_synthetic.mart_journey_summaries;
DROP TABLE IF EXISTS analytics_synthetic.mart_journey_survival;

CREATE TEMP TABLE _synpuf_journey_base AS
WITH input_contract AS (
    SELECT
        COUNT(*) AS total_rows,
        COUNT(DISTINCT claim_id) AS unique_claims,
        SUM(CASE WHEN beneficiary_id IS NOT NULL AND claim_id IS NOT NULL
                      AND CAST(source_release AS VARCHAR) = '2008-2010'
                      AND CAST(evidence_type AS VARCHAR) = 'public_synthetic'
                 THEN 1 ELSE 0 END) AS valid_rows
    FROM raw_synpuf.claims
), source_rows AS (
    SELECT
        CAST(beneficiary_id AS VARCHAR) AS synthetic_id,
        CAST(claim_id AS VARCHAR) AS claim_id,
        CAST(source_release AS VARCHAR) AS source_release,
        CAST(evidence_type AS VARCHAR) AS evidence_type,
        CAST(claim_type AS VARCHAR) AS claim_type,
        CAST(service_from_date AS DATE) AS event_date,
        CAST(service_through_date AS DATE) AS event_through_date,
        CAST(diagnosis_code AS VARCHAR) AS diagnosis_code
    FROM raw_synpuf.claims
    CROSS JOIN input_contract
    WHERE CAST(source_release AS VARCHAR) = '2008-2010'
      AND CAST(evidence_type AS VARCHAR) = 'public_synthetic'
      AND input_contract.total_rows = input_contract.unique_claims
      AND input_contract.total_rows = input_contract.valid_rows
), in_release AS (
    SELECT *
    FROM source_rows
    WHERE event_date BETWEEN DATE '2008-01-01' AND DATE '2010-12-31'
      AND event_through_date BETWEEN DATE '2008-01-01' AND DATE '2010-12-31'
      AND event_through_date >= event_date
), indexed AS (
    SELECT
        in_release.*,
        ROW_NUMBER() OVER (
            PARTITION BY synthetic_id
            ORDER BY event_date, event_through_date, claim_id
        ) AS event_position,
        MIN(event_date) OVER (PARTITION BY synthetic_id) AS index_date
    FROM in_release
), bounded AS (
    SELECT
        indexed.*,
        CAST(LEAST(DATE '2010-12-31', index_date + INTERVAL '365 days') AS DATE) AS follow_up_end
    FROM indexed
    WHERE event_date <= CAST(LEAST(DATE '2010-12-31', index_date + INTERVAL '365 days') AS DATE)
      AND event_through_date <= CAST(
          LEAST(DATE '2010-12-31', index_date + INTERVAL '365 days') AS DATE
      )
), signals AS (
    SELECT
        bounded.*,
        CASE WHEN REPLACE(UPPER(diagnosis_code), '.', '') LIKE '585%'
                  OR REPLACE(UPPER(diagnosis_code), '.', '') LIKE '586%'
                  OR REPLACE(UPPER(diagnosis_code), '.', '') LIKE '588%'
             THEN 1 ELSE 0 END AS is_ckd_signal
    FROM bounded
), target_position AS (
    SELECT
        signals.*,
        MIN(CASE WHEN is_ckd_signal = 1 THEN event_position END)
            OVER (PARTITION BY synthetic_id) AS first_target_position
    FROM signals
), target_dates AS (
    SELECT
        target_position.*,
        MIN(CASE WHEN event_position = first_target_position THEN event_date END)
            OVER (PARTITION BY synthetic_id) AS target_date
    FROM target_position
), persistence AS (
    SELECT
        target_dates.*,
        MIN(CASE
                WHEN is_ckd_signal = 1
                 AND event_date >= target_date + INTERVAL '90 days'
                THEN event_date
            END) OVER (PARTITION BY synthetic_id) AS persistence_date
    FROM target_dates
)
SELECT
    synthetic_id,
    claim_id,
    event_date,
    event_through_date,
    claim_type,
    diagnosis_code,
    CASE
        WHEN event_position = 1 THEN 'index'
        WHEN event_position = first_target_position THEN 'target'
        WHEN first_target_position IS NULL
          OR event_position < first_target_position THEN 'pre_target'
        ELSE 'follow_up'
    END AS event_kind,
    event_position AS event_order,
    is_ckd_signal,
    CASE WHEN event_position = first_target_position THEN TRUE ELSE FALSE END AS is_target_event,
    CASE WHEN persistence_date IS NOT NULL AND event_date = persistence_date
         THEN TRUE ELSE FALSE END AS is_persistence_event,
    index_date,
    target_date,
    persistence_date,
    follow_up_end,
    source_release,
    evidence_type
FROM persistence;

CREATE TABLE analytics_synthetic.mart_journeys AS
SELECT *
FROM _synpuf_journey_base;

CREATE TABLE analytics_synthetic.mart_journey_summaries AS
SELECT
    synthetic_id,
    MIN(index_date) AS index_date,
    MIN(target_date) AS target_date,
    MIN(persistence_date) AS persistence_date,
    MIN(follow_up_end) AS observation_end,
    CAST(
        (CASE WHEN MIN(persistence_date) IS NOT NULL
              AND MIN(persistence_date) <= MIN(follow_up_end)
             THEN MIN(persistence_date) ELSE MIN(follow_up_end) END) - MIN(index_date)
        AS INTEGER
    ) AS duration_days,
    CASE WHEN MIN(persistence_date) IS NOT NULL
              AND MIN(persistence_date) <= MIN(follow_up_end)
         THEN TRUE ELSE FALSE END AS event_observed,
    CASE WHEN MIN(persistence_date) IS NOT NULL
              AND MIN(persistence_date) <= MIN(follow_up_end)
         THEN NULL ELSE 'right_censored_at_follow_up_end' END AS censoring_reason,
    CASE WHEN MIN(target_date) IS NULL THEN FALSE ELSE TRUE END AS has_target,
    'public_synthetic' AS evidence_type
FROM _synpuf_journey_base
GROUP BY synthetic_id;

-- Aggregate durations into risk sets, then calculate a deterministic KM table.
-- The terminal event term contributes zero to Greenwood's sum by convention.
CREATE TABLE analytics_synthetic.mart_journey_survival AS
WITH duration_groups AS (
    SELECT
        duration_days AS time,
        COUNT(*) AS observations,
        SUM(CASE WHEN event_observed THEN 1 ELSE 0 END) AS events,
        SUM(CASE WHEN event_observed THEN 0 ELSE 1 END) AS censored
    FROM analytics_synthetic.mart_journey_summaries
    GROUP BY duration_days
), risk_sets AS (
    SELECT
        duration_groups.*,
        SUM(observations) OVER (
            ORDER BY time ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING
        ) AS at_risk
    FROM duration_groups
), terms AS (
    SELECT
        risk_sets.*,
        MAX(CASE WHEN events = at_risk THEN 1 ELSE 0 END)
            OVER (ORDER BY time ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS had_terminal,
        SUM(CASE WHEN events = at_risk THEN 0.0
            ELSE CAST(events AS DOUBLE PRECISION) / NULLIF(at_risk * (at_risk - events), 0)
            END) OVER (ORDER BY time ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
            AS greenwood_sum,
        SUM(CASE WHEN events = at_risk THEN NULL
                 ELSE LN(1.0 - CAST(events AS DOUBLE PRECISION) / NULLIF(at_risk, 0))
            END) OVER (ORDER BY time ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
            AS log_survival
    FROM risk_sets
)
SELECT
    CAST(time AS DOUBLE PRECISION) AS time,
    CAST(at_risk AS INTEGER) AS at_risk,
    CAST(events AS INTEGER) AS events,
    CAST(censored AS INTEGER) AS censored,
    CASE WHEN had_terminal = 1 THEN 0.0 ELSE EXP(log_survival) END AS survival,
    CASE WHEN had_terminal = 1 THEN 0.0
         ELSE EXP(2.0 * log_survival) * greenwood_sum END AS greenwood_variance,
    CASE WHEN had_terminal = 1 THEN 0.0
         ELSE GREATEST(0.0, EXP(log_survival)
              - 1.959963984540054 * SQRT(EXP(2.0 * log_survival) * greenwood_sum)) END AS ci_low,
    CASE WHEN had_terminal = 1 THEN 0.0
         ELSE LEAST(1.0, EXP(log_survival)
              + 1.959963984540054 * SQRT(EXP(2.0 * log_survival) * greenwood_sum)) END AS ci_high,
    'public_synthetic' AS evidence_type
FROM terms
ORDER BY time;

CREATE TABLE analytics_synthetic.mart_journey_survival_metadata AS
SELECT
    MIN(CASE WHEN survival <= 0.5 THEN time END) AS median_survival,
    'public_synthetic' AS evidence_type
FROM analytics_synthetic.mart_journey_survival;

-- SQL/Python reconciliation contract:
-- * mart_journeys is one row per bounded synthetic claim;
-- * mart_journey_summaries is one row per synthetic beneficiary;
-- * mart_journey_survival contains the same risk/event/censor/Greenwood fields
--   as ckd_intelligence.statistics.time_to_event.kaplan_meier;
-- * mart_journey_survival_metadata persists the median survival method output;
-- * all three tables contain only public_synthetic evidence.
