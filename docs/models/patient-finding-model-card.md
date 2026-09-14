# Patient-finding model card

## Summary

This is a leakage-safe, educational comparison of screening-opportunity methods on
the CDC/NCHS NHANES 2017–2018 public-use cycle. It is not a diagnostic model, a
clinical decision tool, or a patient-targeting system. The outcome is a
cross-sectional laboratory indicator, not confirmed chronic kidney disease (CKD),
because NHANES cannot demonstrate persistence for at least three months.

The retained model is logistic regression. It outperformed the no-skill reference
and had slightly better held-out discrimination than the random-forest comparator.
The tree's added complexity did not produce a performance advantage large enough to
justify selecting it.

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

Numeric imputation, scaling, categorical imputation, and one-hot encoding are fit
inside each development fold. The final preprocessing and model are fit on the
development sample only. The scoring representation requires complete input and
rejects missing, unexpected, forbidden, nonfinite, and out-of-range values.

## Validation design

- Unit of grouping: the combination of NHANES masked variance stratum and PSU.
- Final split: one fold from a shuffled, stratified, grouped five-fold partition is
  held out; no survey cluster appears in both development and holdout samples.
- Development: 4,023 observations across 24 grouped survey clusters.
- Untouched holdout: 993 observations across 6 grouped survey clusters, including
  185 indicator-positive observations (18.63%).
- Threshold selection: the threshold of 0.39835 is selected only from grouped
  out-of-fold logistic-regression predictions in the development sample. It
  represents capacity for approximately 10% of development observations.
- Holdout use: the holdout is evaluated once after preprocessing, model fitting,
  and threshold selection.

This grouped approach reduces direct cluster leakage. With only 30 public survey
clusters, one split can still be variable and should not be treated as external
validation.

## Held-out performance

PR-AUC is interpreted against the held-out prevalence reference of 0.1863.

| Model | ROC-AUC | PR-AUC | Brier score | Precision | Recall |
|---|---:|---:|---:|---:|---:|
| Prevalence/no-skill | 0.5000 | 0.1863 | 0.1516 | 0.0000 | 0.0000 |
| Logistic regression | 0.7550 | 0.4625 | 0.1300 | 0.5625 | 0.2432 |
| Random forest | 0.7433 | 0.4505 | 0.1293 | 0.5495 | 0.2703 |

Precision, recall, and the confusion matrices apply the selected logistic operating
threshold to all model probabilities for a transparent reference. They are not
threshold-optimized separately for each comparator. The no-skill probability is
below this threshold, so it flags no holdout observations.

At the selected threshold, logistic regression flags 80 of 993 held-out
observations (8.06%):

| | Predicted below threshold | Predicted at/above threshold |
|---|---:|---:|
| Indicator negative | 773 | 35 |
| Indicator positive | 140 | 45 |

The held-out flagged share need not equal the 10% development capacity because the
threshold is frozen before holdout evaluation and score distributions can differ.

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
| Age | 60+ | 333 | 116 | 0.5625 | 0.3879 | 0.2060 |
| Sex | Female | 515 | 98 | 0.5217 | 0.2449 | 0.1312 |
| Sex | Male | 478 | 87 | 0.6176 | 0.2414 | 0.1287 |

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

The committed artifact is deterministic JSON rather than pickle. It contains the
logistic intercept and coefficients, development-fitted numeric scaling values,
categorical levels, aggregate metrics, split counts, limitations, and subgroup
diagnostics. It contains no participant rows or identifiers. The scorer is intended
only to demonstrate a validated software boundary and rejects invalid input.

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
