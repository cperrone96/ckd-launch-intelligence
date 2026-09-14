# CMS DE-SynPUF ingestion contract

- Release: 2008–2010 CMS DE-SynPUF
- Population: synthetic Medicare-like beneficiaries in the public sample
- Grain: one synthetic claim or prescription event
- Evidence: public synthetic, always
- Coverage field: `service_from_date`

The adapter preserves synthetic beneficiary and claim identifiers, claim type,
service dates, diagnosis and provider codes, payment amount in U.S. dollars, and year.
It validates date ordering, release coverage, allowed claim types, nonnegative payment,
and claim-key uniqueness.

All valid rows are forcibly labeled `public_synthetic` from the immutable registry.
These records demonstrate software, reconciliation, and journey methods only. They do
not support Medicare population inference and are never linked to observed sources.
