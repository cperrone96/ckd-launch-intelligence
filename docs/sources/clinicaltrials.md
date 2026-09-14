# ClinicalTrials.gov ingestion contract

- Interface: dated envelope containing native ClinicalTrials.gov API v2 study JSON
- Population: registered studies matching the documented CKD query
- Grain: one registered study
- Evidence: public observed
- Coverage field: study `last_update_date`

The JSON snapshot must include `snapshot_metadata.api_version = "v2"`, an ISO-8601
timezone-aware `retrieved_at`, and the exact query
`AREA[ConditionSearch]("Chronic Kidney Disease")`. Its `studies` array preserves the
native API-v2 `protocolSection` module structure. Input is capped at 100 MiB.

The adapter extracts study update date, NCT ID, title, recruitment status, phase,
enrollment, conditions, interventions, sponsor, countries, and study type. It accepts
only documented JSON types: booleans, numbers, arrays, and objects are never silently
stringified into text fields. Malformed individual studies are quarantined without
discarding valid studies. Multi-value API arrays are deterministically joined with a
visible separator in this scalar batch contract.

The snapshot timestamp is retained in the manifest and cannot predate a study's last
update or exceed the registry retrieval date. Submitted records may be incomplete,
delayed, or revised. A bare API response without query/retrieval metadata is rejected
because it cannot prove which search produced the studies.
