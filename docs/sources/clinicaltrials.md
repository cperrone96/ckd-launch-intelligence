# ClinicalTrials.gov CKD landscape contract

- Interface: [ClinicalTrials.gov API v2](https://clinicaltrials.gov/api/v2/studies)
- Population: registered studies matching `AREA[ConditionSearch]("Chronic Kidney Disease")`
- Grain: one registered study, summarized without study identifiers
- Evidence: public observed

The dated snapshot records the exact query, endpoint, page size, request URLs,
page count, total count, retrieval timestamp, and raw SHA-256. All API pages are
retrieved before validation. Retrieval fails closed unless the stable API total,
retrieved row count, and unique valid NCT-ID count all reconcile; duplicate or
missing IDs, repeated page tokens, premature pagination, and total-count drift
are rejected before any snapshot is written. The current snapshot reconciles the
API total to valid plus quarantined records and deduplicates NCT IDs during ingestion.

The aggregate reports status, phase/type, intervention, lead sponsor,
study-country mentions, and update-year change over time. Status, study type, and
update-year denominators use all exact-query studies; phase, intervention, and
location denominators use only studies where that optional field is available.
Missing enrollment is preserved as null and reported separately; it is never
recoded to zero. Registered status, sponsor, geography, and enrollment are
submitted metadata, not patient outcomes or treatment effectiveness. Optional
module omissions become null/unknown; malformed core identity remains quarantined.

The safe output is `data/processed/clinicaltrials_ckd_landscape.json`; its dated
manifest and checksum are committed alongside it. No NCT IDs or raw study rows
are committed in the aggregate.
