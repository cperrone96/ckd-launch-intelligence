# Release notes

## Unreleased — predictor ablation (2026-11-14)

### Added

- **Predictor ablation.** `python -m ckd_intelligence.analysis.predictor_ablation`
  writes `data/processed/patient_finding_predictor_ablation.json`. Four feature sets
  run through the deployed model's nested grouped CV on one shared cohort of 4,321
  adults, where the rule picks plain logistic (0.771). Twenty more survey, exam and
  prescription predictors add +0.009 ROC-AUC (paired 95% CI +0.004 to +0.014). HbA1c
  with hemoglobin adds +0.012 (+0.007 to +0.017). All 22 together add +0.021 (+0.014 to
  +0.027), reaching 0.792 (0.781–0.802).
- **Five more NHANES files** (`GHB_J`, `CBC_J`, `MCQ_J`, `HUQ_J`, `RXQ_RX_J`) under
  their own checksum manifest. Prescription reason codes are never read.

### Unchanged

- The deployed model, its scorer and `patient_finding_model_comparison.json` rebuild
  byte for byte.

## 0.2.0 — 2026-10-23

### Changed results

- **Patient-finding model.** Added five pre-laboratory predictors from public NHANES
  files (BMI, mean systolic blood pressure, self-reported diabetes and hypertension,
  smoking status). Replaced the single 6-PSU holdout with stratified grouped 5-fold
  cross-validation over all 30 PSUs, with 1,000-replicate cluster-bootstrap
  intervals. Four tuned families compete under nested grouped CV, and a declared
  one-standard-error rule on inner log loss selects spline logistic regression:
  ROC-AUC 0.779 (95% CI 0.766–0.791) on 4,741 out-of-fold predictions, +0.039
  (0.026–0.051) over demographics alone. The earlier 0.755 came from one fold whose 6-cluster interval understated
  uncertainty.
- **MEPS variance.** The Diabetes Care Survey population is now a domain of the full
  HC-243 design instead of a subset, which had dropped PSUs and understated standard
  errors by about 3-5%. Estimates match R `survey`. Added spending and utilization by
  kidney-problem status: proxy-positive respondents average USD 10,974 more total
  expenditure per person-year (95% CI 6,172–15,775).
- **Reproducibility.** `scripts/retrieve_surveys.py` downloads and checksum-verifies
  the NHANES and MEPS files; `python -m ckd_intelligence.analysis.nhanes_pipeline`
  rebuilds both NHANES artifacts and their manifests, and notebooks 01-02 call the
  same code.

## 0.1.0 — 2026-09-11

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
  (95% CI 0.390–0.513); paired model differences include zero. (Superseded in
  0.2.0.)
- MEPS diabetes-care proxy-positive prevalence 11.2% among denominator 1,063;
  this is not confirmed CKD.
- ClinicalTrials.gov snapshot: 3,706 registered CKD studies, including 419
  `RECRUITING` and 214 `NOT_YET_RECRUITING`.

### Verification

The release gate passed with 285 tests passing and two explicit PostgreSQL skips;
Ruff and strict mypy were clean. The committed review captures are under
`.impeccable/review/`. CI validates artifacts, OpenAPI/tests, static checks, and
notebook smoke execution without downloading source rows.

### Known limits

This is not a diagnosis, clinical decision tool, patient list, market forecast, or
claim of commercial experience. NHANES and MEPS are source-specific survey panels;
Part D is provider-reported geography; trials are registered-study metadata; and
the synthetic fixture is not representative of Medicare beneficiaries. See the
[risk register](risk-register.md) and [UAT](uat.md) before reuse.
