# ClinicalTrials.gov ingestion contract

- Interface: ClinicalTrials.gov API v2 normalized snapshot
- Population: registered studies matching the documented CKD query
- Grain: one registered study
- Evidence: public observed
- Coverage field: study `last_update_date`

The bounded JSON snapshot must include an ISO-8601 `api_updated_at`, the exact search
query, and normalized study records. The adapter preserves study update date, NCT ID,
title, recruitment status, phase, enrollment, condition, intervention, sponsor,
country, and study type. Codes and NCT uniqueness are validated without silently
normalizing unknown values.

The source update timestamp is retained in the manifest so findings can be tied to a
dated registry snapshot. Submitted records may be incomplete, delayed, or revised.
