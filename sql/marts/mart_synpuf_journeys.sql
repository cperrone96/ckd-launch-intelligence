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
DROP TABLE IF EXISTS analytics_synthetic.mart_journey_survival_metadata;
DROP TABLE IF EXISTS _synpuf_journey_base;

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
    -- Drop claims whose service range covers more than 365 calendar days before
    -- any date is derived, so the index and target are computed exactly once.
    SELECT *
    FROM source_rows
    WHERE event_date BETWEEN DATE '2008-01-01' AND DATE '2010-12-31'
      AND event_through_date BETWEEN DATE '2008-01-01' AND DATE '2010-12-31'
      AND event_through_date >= event_date
      AND event_through_date <= CAST(event_date + INTERVAL '364 days' AS DATE)
), indexed AS (
    SELECT
        in_release.*,
        ROW_NUMBER() OVER (
            PARTITION BY synthetic_id
            ORDER BY event_date, event_through_date, claim_id
        ) AS event_position,
        MIN(event_date) OVER (PARTITION BY synthetic_id) AS index_date,
        CASE WHEN REPLACE(UPPER(diagnosis_code), '.', '') LIKE '585%'
                  OR REPLACE(UPPER(diagnosis_code), '.', '') LIKE '586%'
                  OR REPLACE(UPPER(diagnosis_code), '.', '') LIKE '588%'
             THEN 1 ELSE 0 END AS is_ckd_signal
    FROM in_release
), target_position AS (
    SELECT
        indexed.*,
        MIN(CASE WHEN is_ckd_signal = 1 THEN event_position END)
            OVER (PARTITION BY synthetic_id) AS first_target_position
    FROM indexed
), target_dates AS (
    SELECT
        target_position.*,
        MIN(CASE WHEN event_position = first_target_position THEN event_date END)
            OVER (PARTITION BY synthetic_id) AS target_date
    FROM target_position
), windowed AS (
    -- The time origin is the target date. Follow-up is day 0 through day 364
    -- (365 calendar days), cut at the observation end. People without a
    -- target have no follow-up window and keep every remaining claim.
    SELECT
        target_dates.*,
        CASE WHEN target_date IS NULL THEN NULL
             ELSE CAST(LEAST(DATE '2010-12-31',
                             CAST(target_date + INTERVAL '364 days' AS DATE)) AS DATE)
        END AS follow_up_end
    FROM target_dates
), bounded AS (
    SELECT *
    FROM windowed
    WHERE follow_up_end IS NULL OR event_date <= follow_up_end
), persistence AS (
    SELECT
        bounded.*,
        MIN(CASE
                WHEN is_ckd_signal = 1
                 AND event_date >= CAST(target_date + INTERVAL '90 days' AS DATE)
                THEN event_position
            END) OVER (PARTITION BY synthetic_id) AS persistence_position
    FROM bounded
)
SELECT
    synthetic_id,
    claim_id,
    source_release,
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
    CASE
        WHEN event_position = 1 THEN 0
        WHEN event_position = first_target_position THEN 2
        WHEN first_target_position IS NULL OR event_position < first_target_position THEN 1
        ELSE 3
    END AS event_order,
    is_ckd_signal,
    CASE WHEN event_position = first_target_position THEN TRUE ELSE FALSE END AS is_target_event,
    CASE WHEN event_position = persistence_position
         THEN TRUE ELSE FALSE END AS is_persistence_event,
    index_date,
    target_date,
    CASE WHEN persistence_position IS NOT NULL
         THEN MIN(CASE WHEN event_position = persistence_position THEN event_date END)
              OVER (PARTITION BY synthetic_id)
         ELSE NULL END AS persistence_date,
    follow_up_end,
    evidence_type
FROM persistence;

CREATE TABLE analytics_synthetic.mart_journeys AS
SELECT *
FROM _synpuf_journey_base;

-- One row per person with a target code. Duration is measured from the target
-- date; persistence can only fall inside follow-up because later claims were
-- dropped above. People without a target are not in the risk set.
CREATE TABLE analytics_synthetic.mart_journey_summaries AS
SELECT
    synthetic_id,
    MIN(index_date) AS index_date,
    MIN(target_date) AS target_date,
    MIN(persistence_date) AS persistence_date,
    MIN(follow_up_end) AS observation_end,
    CAST(
        COALESCE(MIN(persistence_date), MIN(follow_up_end)) - MIN(target_date)
        AS INTEGER
    ) AS duration_days,
    CASE WHEN MIN(persistence_date) IS NOT NULL THEN TRUE ELSE FALSE END AS event_observed,
    CASE WHEN MIN(persistence_date) IS NOT NULL
         THEN NULL ELSE 'right_censored_at_follow_up_end' END AS censoring_reason,
    TRUE AS has_target,
    'public_synthetic' AS evidence_type
FROM _synpuf_journey_base
WHERE target_date IS NOT NULL
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
-- * mart_journeys is one row per retained synthetic claim, including people
--   without a target code (their follow_up_end is NULL);
-- * mart_journey_summaries is one row per synthetic beneficiary with a target
--   code, with durations measured from the target date;
-- * mart_journey_survival contains the same risk/event/censor/Greenwood fields
--   as ckd_intelligence.statistics.time_to_event.kaplan_meier;
-- * mart_journey_survival_metadata persists the median survival method output;
-- * all three tables contain only public_synthetic evidence.

DROP TABLE IF EXISTS _synpuf_journey_base;
