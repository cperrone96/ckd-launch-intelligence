# CMS DE-SynPUF ingestion contract

- Release: 2008–2010 CMS DE-SynPUF
- Population: synthetic Medicare-like beneficiaries in the public sample
- Grain: one synthetic claim or prescription event
- Evidence: public synthetic, always
- Coverage field: `service_from_date`

Supported layouts are the repository's normalized CSV and a native single-CSV claims
ZIP whose locator identifies both `2008-2010` and claim type. The native subset uses
`DESYNPUF_ID`, `CLM_ID`, `CLM_FROM_DT`, `CLM_THRU_DT`,
`ADMTNG_ICD9_DGNS_CD`, `PRVDR_NUM`, and `CLM_PMT_AMT`. Compressed input is capped at
512 MiB and its sole CSV member at 2 GiB. Beneficiary-summary and prescription-event
files have different native schemas and are not claimed by this claims adapter.

The adapter preserves synthetic beneficiary and claim identifiers, claim type,
service dates, documented ICD-9/provider code shapes, payment amount in U.S. dollars,
and year. It validates date ordering, 2008–2010 coverage, year/date coherence, allowed
claim types, nonnegative payment, and claim-key uniqueness.

All valid rows are forcibly labeled `public_synthetic` from the immutable registry.
These records demonstrate software, reconciliation, and journey methods only. They do
not support Medicare population inference and are never linked to observed sources.
