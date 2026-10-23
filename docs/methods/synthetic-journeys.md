# CMS DE-SynPUF synthetic journey method

This is a software and statistical-method demonstration using a handcrafted,
schema-compatible `fixture_only` file labeled `public_synthetic` under the CMS
DE-SynPUF 2008–2010 contract. The fixture is not an extract of actual CMS source
rows. It is not a Medicare utilization estimate and must not be generalized to
Medicare beneficiaries.

The notebook calls the production `validate_synpuf_fixture_manifest` boundary
before reading the CSV. It verifies the committed fixture path, SHA-256 digest,
synthetic/fixture-only classification, non-official source-row flag, and the
no-cross-source-join flag.

## Journey contract

- **Spanning claims:** a claim whose service range covers more than 365 calendar
  days (through date more than 364 days after the from date) is dropped before
  any date is derived. The index and target are then computed once from the
  remaining claims, so a dropped claim can never move them or hide a later claim.
- **Index date:** the first remaining `service_from_date` for each synthetic
  beneficiary inside 2008-01-01 through 2010-12-31. It is descriptive only; it is
  not the time origin.
- **Target event:** the first diagnosis code beginning with normalized ICD-9 family
  `585`, `586`, or `588`. Code normalization removes periods and uppercases text.
  This is a small claims-tokenizer demonstration (including the requested Lash-style
  token normalization), not a clinical diagnosis.
- **Chronology:** sort by synthetic beneficiary, event date, through date, then
  claim ID. Claim IDs are the deterministic tie-breaker for same-day events.
- **First-claim target:** when the index claim is itself the first target, the row
  remains `event_kind=index` and is additionally marked `is_target_event=true`; this
  preserves both facts without inventing a duplicate claim event.
- **Time origin:** the target date. Persistence can only happen after the first CKD
  code, so time between the first claim and the first CKD code is event-free by
  construction. Starting the clock at the first claim would add that immortal time
  to every duration and would keep people in the risk set who could never have the
  event.
- **Follow-up window:** 365 calendar days, day 0 (the target date) through day 364,
  so the follow-up end is the earlier of 2010-12-31 and target date plus 364 days.
  Claims dated after the follow-up end are dropped.
- **Persistence event:** a second target signal dated at least 90 days after the
  target date and no later than the follow-up end; exactly 90 days is included.
  Same-day duplicate signals cannot establish this gap.
- **Censoring:** a person with a target and no persistence signal by the follow-up
  end is right-censored at that end date.
- **No target:** a person with eligible claims but no CKD code has no time origin.
  Their claims stay in the event table (as `index`/`pre_target`, with a null
  `follow_up_end`), but they are excluded from the summaries and the Kaplan-Meier
  risk set. `JourneyOutput.excluded_without_target` lists them.
- **Exclusion:** rows with invalid dates, reversed service ranges, duplicate claim
  IDs, missing beneficiary/claim IDs, non-synthetic evidence, or dates outside the
  release window are rejected or excluded before the journey table is built.

The Python builder (`ckd_intelligence.journeys.synpuf`) and the SQL mart
(`sql/marts/mart_synpuf_journeys.sql`) implement the same rules; the tests in
`tests/journeys/test_sql_contract.py` assert that their event, summary and survival
tables are identical on DuckDB.

## Kaplan–Meier contract

The time-to-event input is the number of days from the target date to persistence
or censoring, for people with a target code only. At each unique time, the risk set
includes records whose duration is at least that time; events and censors are
counted separately. Greenwood variance and clipped normal confidence limits are
displayed when requested. CMS synthetic results stay under `analytics_synthetic`;
no observed-source namespace or cross-source/person join is permitted.
