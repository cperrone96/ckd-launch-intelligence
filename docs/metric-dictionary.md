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

Spline logistic regression on eight pre-laboratory predictors: age, sex,
race/ethnicity, BMI, mean systolic blood pressure, self-reported diabetes,
self-reported hypertension and smoking status. It was selected from four tuned
families (L2 logistic, spline logistic, random forest, gradient boosting) by a
one-standard-error rule on inner grouped-CV log loss, nested inside stratified
grouped 5-fold cross-validation over the 30 NHANES masked variance PSUs, on a
4,741-person complete-case cohort (indicator prevalence 18.35%). Every person
receives one out-of-fold prediction.

- Selected model ROC-AUC: 0.779 (95% CI 0.766–0.791); nested estimate of the whole
  selection procedure 0.773 (0.759–0.786).
- PR-AUC: 0.484 (95% CI 0.453–0.518); no-skill reference 0.184.
- Brier score: 0.1223 (95% CI 0.1154–0.1293); no-skill reference 0.1498.
- Top-10% operating point: 474 of 4,741 flagged; precision 0.561, recall 0.306.
- Gain over demographics only: +0.039 ROC-AUC (95% CI 0.026–0.051).
- Tuned random forest: 0.781 ROC-AUC; spline minus forest −0.002
  (95% CI −0.008 to +0.004).
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

Six utilization measures are contrasted; total expenditure is the headline
measure. After a Bonferroni correction for six comparisons (alpha 0.0083), the
expenditure (p = 1e-5), inpatient-stay, office-visit and prescription differences
remain significant; the emergency-visit (p = 0.047) and outpatient differences do
not.

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
