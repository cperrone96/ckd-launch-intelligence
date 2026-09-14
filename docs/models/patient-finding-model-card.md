# Patient-finding model card

## Summary

This is a leakage-safe, educational comparison of screening-opportunity methods on
the CDC/NCHS NHANES 2017–2018 public-use cycle. It is not a diagnostic model, a
clinical decision tool, or a patient-targeting system. The outcome is a
cross-sectional laboratory indicator, not confirmed chronic kidney disease (CKD),
because NHANES cannot demonstrate persistence for at least three months.

Logistic regression is the pre-specified primary model because interpretability is
the appropriate default for this educational use case. This choice was fixed before
holdout evaluation. The random forest is a comparator, not a candidate selected by
looking at the holdout. Paired cluster-bootstrap intervals include zero for every
logistic-versus-forest difference, so no reliable advantage between those two models
is established.

## Data and cohort

- Source: exact, checksummed CDC/NCHS `DEMO_J`, `BIOPRO_J`, and `ALB_CR_J` public-use
  files listed in `data/manifests/nhanes-2017-2018-patient-need.json`.
- Population represented by the analytic source: NHANES 2017–2018 MEC-examined
  U.S. civilian, noninstitutionalized adults, excluding known pregnancy.
- Model analytic sample: 5,016 adults with evaluable eGFR and UACR.
- Primary outcome: race-free 2021 CKD-EPI creatinine eGFR below 60
  mL/min/1.73 m² or UACR at least 30 mg/g, with both measures required.
- Model evaluation is unweighted. It describes the held-out analytic sample and is
  not a U.S. population-performance estimate. Task 3 contains survey-weighted
  patient-need estimates.
- No source is linked to another source at person level. No raw participant row,
  `SEQN`, or other row identifier is committed in the model artifact.

## Leakage controls and inputs

The locally available verified source provides only three defensible
pre-laboratory predictors for this task:

- age in years;
- sex recorded in NHANES;
- race/ethnicity category recorded in NHANES.

The implementation uses a strict allowlist. It rejects creatinine, eGFR, UACR,
urine albumin, urine creatinine, the CKD indicator, renal-function fields,
cystatin C, proteinuria, blood urea nitrogen, dialysis history, and names suggesting
transformed versions of those variables. Identifier and weight fields are also not
eligible predictors.

Race/ethnicity is a social and administrative category, not a biological cause.
Its inclusion demonstrates categorical preprocessing and should not be interpreted
as justification for race-based care. No subgroup assessment in this small,
single-cycle analysis constitutes fairness certification.

Numeric scaling and categorical one-hot encoding are fit inside each development
fold. The final preprocessing and model are fit on the development sample only.
Missing values are rejected consistently during training and scoring; the artifact
does not claim or perform imputation. It also rejects unexpected, forbidden,
nonfinite, unknown-category, and out-of-range values.

## Validation design

- Unit of grouping: the combination of NHANES masked variance stratum and PSU.
- Final split: one fold from a shuffled, stratified, grouped five-fold partition is
  held out; no survey cluster appears in both development and holdout samples.
- Development: 4,023 observations across 24 grouped survey clusters.
- Untouched holdout: 993 observations across 6 grouped survey clusters, including
  185 indicator-positive observations (18.63%).
- Development operating reference: 0.39835, selected only from grouped out-of-fold
  logistic-regression predictions. The deterministic policy selects exactly 402 of
  4,023 development observations (9.99%) and never exceeds capacity.
- Capacity-matched holdout comparison: each model ranks holdout probabilities
  without using holdout labels, then selects exactly 99 of 993 observations. Ties
  resolve by descending probability followed by stable row order, so capacity is
  never exceeded. Realized probability boundaries differ by model.
- Holdout use: the holdout is evaluated once after preprocessing, model fitting,
  pre-specifying the primary model, and creating the development operating reference.
- Uncertainty: 1,000 deterministic percentile bootstrap replicates resample the six
  holdout survey clusters with replacement. These intervals quantify sampling
  variation within this split but remain imprecise because only six holdout clusters
  are available.

This grouped approach reduces direct cluster leakage. With only 30 public survey
clusters, one split can still be variable and should not be treated as external
validation.

## Held-out performance

PR-AUC is interpreted against the held-out prevalence reference of 0.1863.

| Model | ROC-AUC (95% CI) | PR-AUC (95% CI) | Brier (95% CI) | Precision (95% CI) | Recall (95% CI) |
|---|---:|---:|---:|---:|---:|
| Prevalence/no-skill | 0.5000 (0.5000–0.5000) | 0.1863 (0.1617–0.2100) | 0.1516 (0.1362–0.1664) | 0.2222 (0.1644–0.3205) | 0.1189 (0.1071–0.1300) |
| Logistic regression | 0.7550 (0.7081–0.7809) | 0.4625 (0.3903–0.5135) | 0.1300 (0.1196–0.1388) | 0.5354 (0.4724–0.6027) | 0.2865 (0.2276–0.3407) |
| Random forest | 0.7433 (0.7065–0.7723) | 0.4505 (0.3713–0.5155) | 0.1293 (0.1188–0.1372) | 0.5455 (0.4766–0.6211) | 0.2919 (0.2345–0.3547) |

Precision, recall, and confusion matrices use the same exact 99-observation capacity
for every model. The no-skill scores are all tied, so its selected set is an explicit,
deterministic ordering reference rather than a meaningful ranking.

At the capacity-matched boundary of 0.38224, logistic regression flags exactly 99 of
993 held-out observations (9.97%):

| | Predicted below threshold | Predicted at/above threshold |
|---|---:|---:|
| Indicator negative | 762 | 46 |
| Indicator positive | 132 | 53 |

The development threshold remains separately recorded for future fixed-threshold
demonstrations. The table above instead uses the fair, exact-capacity policy so ties
and different model score scales cannot silently exceed the operating limit.

Paired logistic-minus-random-forest differences are small and uncertain:

- ROC-AUC: 0.0117 (95% CI −0.0096 to 0.0325).
- PR-AUC: 0.0120 (95% CI −0.0053 to 0.0255).
- Brier score: 0.0007 (95% CI −0.0021 to 0.0032; lower is better).

Every interval includes zero. The holdout therefore supports the pre-specified
interpretability decision, not a performance-superiority claim.

## Calibration

The logistic Brier score is 0.1300 versus 0.1516 for the prevalence reference. Five
equal-count holdout bins show the following mean predicted and observed rates:

| Bin n | Mean predicted | Observed |
|---:|---:|---:|
| 200 | 0.0417 | 0.0450 |
| 199 | 0.0802 | 0.0905 |
| 197 | 0.1454 | 0.1574 |
| 199 | 0.2347 | 0.1859 |
| 198 | 0.3825 | 0.4545 |

The middle and highest bins show miscalibration that is material for probability
interpretation. No post-hoc calibration was fit because this single-cycle sample is
better used to demonstrate honest diagnostics than to imply clinical readiness.

## Subgroup diagnostics

These are descriptive holdout checks using the same frozen threshold.

| Dimension | Group | n | Events | Precision | Recall | Brier |
|---|---|---:|---:|---:|---:|---:|
| Age | 18–39 | 344 | 18 | undefined (no flags) | 0.0000 | 0.0496 |
| Age | 40–59 | 316 | 51 | undefined (no flags) | 0.0000 | 0.1374 |
| Age | 60+ | 333 | 116 | 0.5354 | 0.4569 | 0.2060 |
| Sex | Female | 515 | 98 | 0.5000 | 0.2857 | 0.1312 |
| Sex | Male | 478 | 87 | 0.5814 | 0.2874 | 0.1287 |

Cluster-bootstrap uncertainty is included for subgroup precision, recall, and Brier
score in the JSON artifact; intervals carry an explicit six-cluster limitation.
The model flags no one in either younger age band at this capacity threshold. That
is an important operational limitation, not evidence that screening is unnecessary
in those groups. Age is the strongest available signal, so the model largely
concentrates capacity among adults aged 60 or older.

## Outcome-definition sensitivity

Applying the same primary-outcome model probabilities to alternative laboratory
definitions changes both prevalence and apparent discrimination:

| Holdout definition | n | Prevalence | ROC-AUC | PR-AUC |
|---|---:|---:|---:|---:|---:|
| Primary eGFR or albuminuria | 993 | 0.1863 | 0.7550 | 0.4625 |
| eGFR only | 993 | 0.0806 | 0.8782 | 0.4258 |
| Albuminuria only | 993 | 0.1450 | 0.6957 | 0.3072 |

This is a sensitivity analysis, not retraining or independent validation. The
stronger eGFR-only ranking is consistent with age being an input and a component of
the eGFR equation; it is another reason not to interpret this model causally.

## Scoring artifact and reproducibility

The committed artifact is deterministic, strict JSON rather than pickle. It contains
a semantic version, required-field types/ranges/categories, explicit reject policies
for missing and unknown inputs, float64 coefficient precision, ordered features and
categories, the logistic intercept and coefficients, development-fitted scaling,
aggregate metrics, uncertainty, split counts, limitations, and subgroup diagnostics.
It embeds the Task 3 source-manifest path, release, retrieval date, URLs, byte counts,
and SHA-256 digests. A validated loader rejects inconsistent or tampered contracts,
and full-vector tests reproduce the fitted pipeline's holdout probabilities to
numerical tolerance. It contains no participant rows or identifiers.

Run:

```bash
.venv/bin/jupyter-nbconvert --to notebook --execute --inplace \
  --ClearMetadataPreprocessor.enabled=True notebooks/02_patient_finding.ipynb \
  --ExecutePreprocessor.timeout=240
shasum -a 256 -c data/processed/patient_finding_model_comparison.sha256
```

If the verified raw cache is unavailable, the notebook uses a deterministic,
expanded fixture and writes only to
`data/processed/fixture/patient_finding_model_comparison_fixture.json`. Fixture
execution cannot overwrite the official aggregate artifact and is never presented
as a population finding.

## Prohibited uses and limitations

- Do not use for diagnosis, treatment, outreach, eligibility, coverage, or any
  decision about an individual.
- Do not interpret associations as causal or race/ethnicity as biological risk.
- Do not generalize beyond the documented public-use cycle and analytic cohort.
- A single serum-creatinine result and spot UACR cannot confirm chronic CKD.
- Complete-case selection can bias performance if missing laboratory measures are
  systematic.
- Survey weights are not used in model training or performance metrics.
- Grouped internal holdout evaluation is not temporal, geographic, prospective, or
  external validation.
- Small event counts, especially in younger age bands, limit subgroup inference.
- The available pre-lab feature set is deliberately narrow and omits medical
  history, symptoms, medications, and care context.
