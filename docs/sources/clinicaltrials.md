# ClinicalTrials.gov CKD landscape contract

- Interface: [ClinicalTrials.gov API v2](https://clinicaltrials.gov/api/v2/studies)
- Population: registered studies matching `AREA[ConditionSearch]("Chronic Kidney Disease")`
- Grain: one registered study, summarized without study identifiers
- Evidence: public observed

The dated snapshot records the exact query, endpoint, page size, request URLs,
page count, total count, retrieval timestamp, and raw SHA-256. All API pages are
retrieved before validation. The current snapshot reconciles the API total to
valid plus quarantined records and deduplicates NCT IDs during ingestion.

The aggregate reports status, phase/type, lead sponsor, study-country mentions,
and update-year change over time. Missing enrollment is preserved as null and
reported separately; it is never recoded to zero. Registered status, sponsor,
geography, and enrollment are submitted metadata, not patient outcomes or
treatment effectiveness. Malformed modules are quarantined with reasons rather
than silently coerced.

The safe output is `data/processed/clinicaltrials_ckd_landscape.json`; its dated
manifest and checksum are committed alongside it. No NCT IDs or raw study rows
are committed in the aggregate.
