# Metric dictionary

## Patient need

The primary indicator is `eGFR < 60 mL/min/1.73 m² OR UACR >= 30 mg/g`, requiring
both defining laboratory measures. eGFR uses the race-free 2021 CKD-EPI creatinine
equation and UACR uses the documented NHANES albumin-creatinine ratio field.

- **Estimate:** 13.9189%, displayed as 13.9%.
- **Denominator:** 5,016 complete-case MEC-examined adults.
- **Uncertainty:** 95% CI 12.5326%–15.3051%, displayed as 12.5%–15.3%.
- **Method:** 2-year MEC weights and Taylor linearization for a stratified PSU ratio;
  15 design degrees of freedom, 30 PSUs, 15 strata.
- **Boundary:** cross-sectional complete-case survey-domain signal, not a persistent
  CKD prevalence estimate, diagnosis, or patient list. Missing labs are unknown.

Sensitivity definitions are `eGFR only` and `albuminuria only`; they use the same
complete-case domain so definition sensitivity is not confused with availability.

## Patient finding model comparison

The primary model is pre-specified logistic regression using age, sex, and
race/ethnicity. A grouped survey-cluster split holds out 993 observations from the
5,016-person analytic cohort. The held-out outcome prevalence is 18.63%.

- Logistic ROC-AUC: 0.7550 (95% CI 0.7081–0.7809).
- Logistic PR-AUC: 0.4625 (95% CI 0.3903–0.5135).
- Logistic Brier score: 0.1300 (95% CI 0.1196–0.1388).
- Exact-capacity holdout review: 99 of 993 ranked observations selected; precision
  0.5354 and recall 0.2865 in the stored comparison.
- Uncertainty: 1,000 deterministic holdout cluster-bootstrap replicates; only six
  holdout clusters, so interval precision is limited.

The random forest is a comparator and prevalence/no-skill is a reference. Every
paired model difference interval includes zero, so the release does not claim model
superiority. The score endpoint is a non-diagnostic educational scorer and does not
return a patient list or support care decisions or targeting.

## Care and prescribing context

MEPS reports a diabetes-care proxy domain, not confirmed CKD:

- Proxy-positive prevalence: 11.18% (displayed as 11.2%), denominator 1,063.
- Average office visits: 12.25 per person-year.
- Average total expenditure: USD 16,746 per person-year.

These are descriptive HC-243 person-year estimates with MEPS design variables and
Taylor uncertainty. Part D is a selected-generic, provider/drug/provider-state
aggregate. It cannot establish CKD indication, beneficiary residence, adherence,
outcomes, or a patient journey.

## Trial landscape

The exact ClinicalTrials.gov API v2 condition query reconciles to 3,706 registered
studies. The snapshot reports 419 `RECRUITING` and 214 `NOT_YET_RECRUITING` studies.
These are registry status counts. They are not a measure of treatment effectiveness,
enrollment success, patient demand, or available care.

## Opportunity scenario

The score is a weighted sum of min–max-normalized `need`, `screening_gap`,
`prescribing`, and `trial_activity` components. Eligibility is decided before
normalization; coverage below the explicit threshold or any missing component makes
a row unscorable. Missing is never zero. Weights must sum exactly to one, ranks are
deterministic, and alternative weight sets report rank sensitivity.

This is a scenario-only method. The dashboard deliberately does not present an
observed geographic composite because the source families have incompatible
geography, time, and population definitions.
