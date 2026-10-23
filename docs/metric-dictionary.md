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

Logistic regression (pre-specified) on eight pre-laboratory predictors: age, sex,
race/ethnicity, BMI, mean systolic blood pressure, self-reported diabetes,
self-reported hypertension and smoking status. Evaluated with stratified grouped
5-fold cross-validation over the 30 NHANES masked variance PSUs on a 4,741-person
complete-case cohort (indicator prevalence 18.35%). Every person receives one
out-of-fold prediction.

- Logistic ROC-AUC: 0.772 (95% CI 0.759–0.784).
- Logistic PR-AUC: 0.464 (95% CI 0.436–0.494); no-skill reference 0.184.
- Logistic Brier score: 0.124 (95% CI 0.118–0.131); no-skill reference 0.150.
- Top-10% operating point: 474 of 4,741 flagged; precision 0.557, recall 0.303.
- Gain over demographics only: +0.031 ROC-AUC (95% CI 0.018–0.045).
- Random forest comparator: 0.780 ROC-AUC; difference vs logistic −0.008
  (95% CI −0.014 to −0.003).
- Uncertainty: 1,000 cluster-bootstrap replicates over the 30 PSUs, paired across
  models; fold models are held fixed.

Metrics are unweighted analytic-cohort performance, not population performance.
See the [model card](models/patient-finding-model-card.md) for calibration,
subgroups and definitions.

## Care and prescribing context

MEPS reports a diabetes-care proxy domain, not confirmed CKD. The Diabetes Care
Survey population is estimated as a domain of the full HC-243 design (22,431
records, 364 PSUs, 105 strata).

- Proxy-positive prevalence: 11.18% (95% CI 8.97%–13.39%), denominator 1,063.
- Average total expenditure, all DCS diabetes respondents: USD 16,746 per
  person-year (95% CI 15,192–18,301).
- Proxy-positive vs proxy-negative total expenditure: USD 26,494 vs USD 15,520;
  difference USD 10,974 (95% CI 6,172–15,775).
- Proxy-positive vs proxy-negative inpatient stays: 0.39 vs 0.13 per person-year;
  office visits: 21.5 vs 11.1.

These are descriptive HC-243 person-year estimates with Taylor-linearized
uncertainty; the contrast is an association, not a causal effect of kidney
problems. Part D is a selected-generic, provider/drug/provider-state aggregate. It
cannot establish CKD indication, beneficiary residence, adherence, outcomes, or a
patient journey.

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
