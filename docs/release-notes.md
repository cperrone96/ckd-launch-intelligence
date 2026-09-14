# Release notes

## CKD Launch Intelligence 0.1.0 review — 2026-09-11

This portfolio release packages public-data analysis as a reproducible, offline
API and evidence-led dashboard. It is educational and contains no customer,
employer, client, or proprietary business data.

### Included

- NHANES 2017–2018 weighted patient-need estimates with survey design and
  uncertainty retained.
- Leakage-safe NHANES model comparison with held-out performance, calibration,
  subgroup diagnostics, and a non-diagnostic scorer contract.
- MEPS HC-243 2022 care/utilization context, CMS Part D selected-generic context,
  and a fully reconciled ClinicalTrials.gov CKD registry snapshot.
- A transparent opportunity-scenario method that rejects incompatible geography,
  time, coverage, and evidence inputs instead of emitting a misleading composite.
- A checksum- and manifest-verified FastAPI contract with strict OpenAPI schemas,
  structured errors, bounded filters/pagination, and identifier-free aggregates.
- A Dash dashboard with source-specific evidence pages, explicit empty/error/loading
  states, responsive navigation, accessible table alternatives, and visible
  synthetic/non-diagnostic limitations.
- A deterministic CMS DE-SynPUF-compatible journey demonstration using a committed
  handcrafted fixture, clearly labeled `public_synthetic` and `fixture_only`.

### Reviewed findings

- NHANES primary cross-sectional indicator: 13.9% (95% CI 12.5–15.3%), denominator
  5,016 complete-case records.
- Logistic held-out ROC-AUC 0.755 (95% CI 0.708–0.781) and PR-AUC 0.462
  (95% CI 0.390–0.513); paired model differences include zero.
- MEPS diabetes-care proxy-positive prevalence 11.2% among denominator 1,063;
  this is not confirmed CKD.
- ClinicalTrials.gov snapshot: 3,706 registered CKD studies, including 419
  `RECRUITING` and 214 `NOT_YET_RECRUITING`.

### Verification

The release gate passed with 257 tests passing and two explicit PostgreSQL skips;
Ruff and strict mypy were clean. The committed review captures are under
`.impeccable/review/`. CI validates artifacts, OpenAPI/tests, static checks, and
notebook smoke execution without downloading source rows.

### Known limits

This is not a diagnosis, clinical decision tool, patient list, market forecast, or
claim of commercial experience. NHANES and MEPS are source-specific survey panels;
Part D is provider-reported geography; trials are registered-study metadata; and
the synthetic fixture is not representative of Medicare beneficiaries. See the
[risk register](risk-register.md) and [UAT](uat.md) before reuse.
