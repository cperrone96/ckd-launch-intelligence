# CMS DE-SynPUF synthetic journey method

This is a software and statistical-method demonstration using the CMS DE-SynPUF
2008–2010 public synthetic sample. It is not a Medicare utilization estimate and
must not be generalized to Medicare beneficiaries.

## Journey contract

- **Index date:** the first valid `service_from_date` for each synthetic beneficiary
  inside 2008-01-01 through 2010-12-31.
- **Target event:** the first diagnosis code beginning with normalized ICD-9 family
  `585`, `586`, or `588`. Code normalization removes periods and uppercases text.
  This is a small claims-tokenizer demonstration (including the requested Lash-style
  token normalization), not a clinical diagnosis.
- **Chronology:** sort by synthetic beneficiary, event date, through date, then
  claim ID. Claim IDs are the deterministic tie-breaker for same-day events.
- **Follow-up end:** the earlier of 2010-12-31 and index date plus 365 days.
- **Persistence event:** a second target signal at least 90 days after the first;
  exactly 90 days is included. Same-day duplicate signals cannot establish this
  gap.
- **Censoring:** no persistence signal by follow-up end is right-censored at that
  end date. A beneficiary with a target but no persistence remains in the survival
  denominator; a beneficiary without a target is retained as a censored method
  demonstration.
- **Exclusion:** rows with invalid dates, reversed service ranges, duplicate claim
  IDs, missing beneficiary/claim IDs, non-synthetic evidence, or dates outside the
  release window are rejected or excluded before the journey table is built.

## Kaplan–Meier contract

The time-to-event input is duration from index date to persistence or censoring.
At each unique time, the risk set includes records whose duration equals that time;
events and censors are counted separately. Greenwood variance and clipped normal
confidence limits are displayed when requested. CMS synthetic results stay under
`analytics_synthetic`; no observed-source namespace or cross-source/person join is
permitted.
