# Patient-finding model card

All numbers below come from `data/processed/patient_finding_model_comparison.json`,
built by `python -m ckd_intelligence.analysis.nhanes_pipeline` (or notebook 02).

## Summary

The model ranks NHANES 2017-2018 adults by their probability of a cross-sectional
CKD laboratory indicator (eGFR <60 or UACR ≥30 mg/g) using only information that is
available before kidney labs are drawn. It estimates screening yield for a
population, not a diagnosis for a person.

The selected model is a **spline logistic regression**: cubic B-splines for age,
BMI and systolic blood pressure, one-hot categories and an L2 penalty. It was chosen
by a rule declared in code before the nested run (below), not by its outer-fold
score. On pooled out-of-fold predictions it reaches ROC-AUC 0.779 (95% CI
0.766–0.791), the best PR-AUC (0.484) and Brier score (0.1223) of the four tuned
families. No tuned rival is reliably better: the random forest is 0.002 ROC-AUC
higher with a paired interval that includes zero (−0.008 to +0.004). The selection
was close, so the nested estimate of the whole procedure, ROC-AUC 0.773
(0.759–0.786), is the conservative number to quote.

## Data and cohort

- Source: checksummed CDC/NCHS public-use files `DEMO_J`, `BIOPRO_J`, `ALB_CR_J`,
  `BMX_J`, `BPX_J`, `DIQ_J`, `BPQ_J` and `SMQ_J`, listed in
  `data/manifests/nhanes-2017-2018-patient-need.json` and joined one-to-one on `SEQN`.
- Indicator domain: 5,016 MEC-examined adults (18+, excluding known pregnancy) with
  both eGFR and UACR.
- Model cohort: 4,741 adults with every predictor present (275 excluded; systolic
  blood pressure is the main gap with 219 missing). Indicator prevalence 18.4%.
- Outcome: race-free CKD-EPI 2021 creatinine eGFR <60 mL/min/1.73 m² or UACR
  ≥30 mg/g. One visit cannot show 3-month persistence, so this is an indicator,
  not confirmed CKD.
- Metrics are unweighted and describe this analytic cohort. The survey-weighted
  population estimate is in `patient_need_summary.json`.

## Predictors and leakage controls

| Predictor | NHANES source | Coding |
|---|---|---|
| Age | `RIDAGEYR` | years |
| Sex | `RIAGENDR` | Female, Male |
| Race/ethnicity | `RIDRETH3` | six NHANES categories |
| Body mass index | `BMXBMI` | kg/m² |
| Systolic blood pressure | `BPXSY1`-`BPXSY4` | mean of available readings |
| Diabetes history | `DIQ010` | Yes, No, Borderline |
| Hypertension history | `BPQ020` | Yes, No |
| Smoking status | `SMQ020`, `SMQ040` | Never, Former, Current |

Refused or don't-know answers are missing, never "No". The feature builder enforces
an allowlist and rejects any column whose name refers to creatinine, eGFR, albumin,
UACR, cystatin, urea, proteinuria, dialysis or the indicator itself. Scaling and
one-hot encoding are fit inside each training fold.

Race/ethnicity is a social category, not a biological cause; it is included as a
recorded demographic and its coefficient should not be read as biology.

## Validation design and model selection

- Stratified grouped 5-fold cross-validation. The 30 NHANES masked variance PSUs
  (stratum × PSU) are the groups, so no PSU is in both a fitting and a scoring fold.
  Each fold scores 6 PSUs (919–979 people); every person receives one
  out-of-fold prediction. All models use the same folds.
- Four families compete: L2 logistic regression, spline logistic regression,
  random forest and histogram gradient boosting. Inside every outer fit set each is
  tuned by grid search on an inner grouped 5-fold CV, scored by log loss (a proper
  scoring rule, so calibration counts as well as ranking).
- **Selection rule, declared before the nested run:** take the simplest family
  (order: logistic, spline logistic, random forest, gradient boosting) whose mean
  inner log loss is within one standard error of the best family's. The outer
  folds only measure the result. The same rule run on the full cohort picks the
  deployed model.
- On the full cohort the inner log losses were spline 0.3935 (SE 0.0050), random
  forest 0.3944, gradient boosting 0.3947 and plain logistic 0.4005. Plain logistic
  falls outside one SE of the best, so the spline is selected. Inside the outer
  folds the rule picked plain logistic in 4 of 5 fit sets, which is why the
  procedure estimate (0.773) sits below the spline's own score (0.779).
- Grids and per-fold choices are stored under `tuning` in the artifact. A
  convergence warning from any optimizer is raised as an error, so a non-converged
  fit can't produce platform-dependent numbers.
- Baselines: a demographics-only logistic model and a constant score at the cohort
  prevalence (no-skill reference).
- Uncertainty: 1,000 cluster-bootstrap replicates resample the 30 PSUs. Model
  differences are computed on the same replicates (paired). Fold models are held
  fixed, so intervals exclude refitting variability.
- Operating point: the top 10% of out-of-fold scores (474 of 4,741), ranked without
  labels; ties break by stable row order. The resulting score boundary (0.453) is
  the API's flag threshold for the final model, which is refit on all 4,741 people.

## Performance (pooled out-of-fold, n = 4,741)

| Model | ROC-AUC (95% CI) | PR-AUC (95% CI) | Brier (95% CI) | Precision at top 10% | Recall at top 10% |
|---|---|---|---|---|---|
| Spline logistic regression, tuned (selected) | 0.779 (0.766–0.791) | 0.484 (0.453–0.518) | 0.1223 (0.1154–0.1293) | 0.561 (0.525–0.596) | 0.306 (0.288–0.326) |
| Random forest, tuned | 0.781 (0.769–0.792) | 0.476 (0.448–0.506) | 0.1227 (0.1159–0.1291) | 0.557 (0.524–0.595) | 0.303 (0.280–0.337) |
| Gradient boosting, tuned | 0.776 (0.764–0.789) | 0.475 (0.443–0.511) | 0.1230 (0.1163–0.1295) | 0.551 (0.505–0.594) | 0.300 (0.280–0.321) |
| Logistic regression, tuned L2 | 0.772 (0.759–0.784) | 0.466 (0.437–0.496) | 0.1243 (0.1178–0.1309) | 0.551 (0.505–0.596) | 0.300 (0.280–0.320) |
| Selection procedure, nested estimate | 0.773 (0.759–0.786) | 0.469 (0.437–0.499) | 0.1240 (0.1174–0.1307) | 0.551 (0.506–0.592) | 0.300 (0.280–0.321) |
| Logistic regression, demographics only | 0.741 (0.725–0.757) | 0.412 (0.383–0.445) | 0.1312 (0.1244–0.1380) | 0.511 (0.463–0.554) | 0.278 (0.257–0.301) |
| No-skill reference (constant prevalence) | 0.500 | 0.184 (0.170–0.196) | 0.1498 | not meaningful (tied scores) | not meaningful |

At the 10% operating point the selected model flags people with the indicator at
3.1 times the base rate (precision 0.561 vs prevalence 0.184) and finds 31% of them
(266 true positives, 208 false positives, 604 false negatives).

### Paired differences (selected spline logistic minus rival, same replicates)

| Rival | ROC-AUC | PR-AUC | Brier |
|---|---|---|---|
| Random forest | -0.002 (-0.008 to +0.004) | +0.009 (-0.003 to +0.018) | -0.0004 (-0.0019 to +0.0011) |
| Gradient boosting | +0.003 (-0.001 to +0.008) | +0.009 (-0.001 to +0.019) | -0.0008 (-0.0019 to +0.0003) |
| Logistic regression (L2) | +0.007 (+0.001 to +0.013) | +0.018 (+0.006 to +0.030) | -0.0021 (-0.0032 to -0.0008) |
| Demographics only | +0.039 (+0.026 to +0.051) | +0.072 (+0.044 to +0.099) | -0.0089 (-0.0119 to -0.0060) |

### Calibration (selected model, out-of-fold quintiles)

| n | Mean predicted | Observed |
|---|---|---|
| 949 | 0.049 | 0.060 |
| 948 | 0.069 | 0.054 |
| 948 | 0.108 | 0.101 |
| 948 | 0.208 | 0.239 |
| 948 | 0.483 | 0.463 |

Predicted and observed rates stay within about three percentage points in every
quintile.

### Subgroups at the 10% operating point

| Group | n | Positives | Prevalence | Mean predicted | ROC-AUC | Flagged | Precision | Recall |
|---|---|---|---|---|---|---|---|---|
| Age 18-39 | 1,552 | 107 | 0.069 | 0.067 | 0.587 | 0.1% | none positive | 0.000 |
| Age 40-59 | 1,453 | 186 | 0.128 | 0.134 | 0.718 | 1.3% | 0.684 | 0.070 |
| Age 60+ | 1,736 | 577 | 0.332 | 0.329 | 0.722 | 26.2% | 0.557 | 0.438 |
| Diabetes: Borderline | 150 | 28 | 0.187 | 0.190 | 0.660 | 8.7% | 0.538 | 0.250 |
| Diabetes: No | 3,869 | 533 | 0.138 | 0.138 | 0.749 | 4.4% | 0.541 | 0.173 |
| Diabetes: Yes | 722 | 309 | 0.428 | 0.427 | 0.673 | 40.3% | 0.574 | 0.540 |
| Hypertension: No | 2,990 | 311 | 0.104 | 0.104 | 0.703 | 1.6% | 0.574 | 0.087 |
| Hypertension: Yes | 1,751 | 559 | 0.319 | 0.320 | 0.723 | 24.4% | 0.560 | 0.428 |
| Mexican American | 668 | 100 | 0.150 | 0.150 | 0.744 | 6.3% | 0.500 | 0.210 |
| Non-Hispanic Asian | 662 | 93 | 0.140 | 0.143 | 0.733 | 5.0% | 0.455 | 0.161 |
| Non-Hispanic Black | 1,054 | 236 | 0.224 | 0.225 | 0.787 | 14.4% | 0.632 | 0.407 |
| Non-Hispanic White | 1,665 | 334 | 0.201 | 0.199 | 0.790 | 12.3% | 0.544 | 0.332 |
| Other Hispanic | 437 | 63 | 0.144 | 0.145 | 0.760 | 5.0% | 0.591 | 0.206 |
| Other Race - Including Multi-Racial | 255 | 44 | 0.173 | 0.173 | 0.793 | 8.2% | 0.476 | 0.227 |
| Female | 2,423 | 442 | 0.182 | 0.182 | 0.756 | 10.4% | 0.546 | 0.310 |
| Male | 2,318 | 428 | 0.185 | 0.185 | 0.803 | 9.6% | 0.578 | 0.301 |

Mean predicted risk matches observed prevalence in every subgroup
(calibration-in-the-large). Age drives the ranking: a single 10% capacity flags
almost no one under 40, so the 107 indicator-positive young adults are all missed.
Serving that group would need a separate threshold or a different screening policy.
Within-group ROC-AUC is lower among people with diabetes (0.673), where risk is
already high across the group and harder to separate.

### Indicator-definition sensitivity (same out-of-fold scores)

| Definition | Prevalence | ROC-AUC | PR-AUC |
|---|---|---|---|
| eGFR <60 or UACR ≥30 (primary) | 0.184 | 0.779 | 0.484 |
| eGFR <60 only | 0.081 | 0.858 | 0.343 |
| UACR ≥30 only | 0.133 | 0.727 | 0.338 |

Low eGFR is easier to rank from age and blood pressure than albuminuria is.

## Scoring artifact

The deployable scorer is strict JSON, not pickle: ordered features, category
levels, the B-spline knot vectors for the three numeric predictors, 37
coefficients and an intercept, with explicit reject policies for missing, unknown
and out-of-range inputs. Numeric values beyond the training range take the
boundary value, as scikit-learn's `SplineTransformer` does. The API's
`/api/v1/patient-finding/score` endpoint validates every field before scoring. A
test checks that the JSON scorer reproduces the fitted scikit-learn pipeline to
1e-10. If the rule ever selects a tree model, the build fails rather than shipping
a scorer that doesn't match the reported model.

## Limitations

- Cross-sectional indicator, not chronic CKD; a single creatinine and spot UACR
  carry biological and measurement variability.
- Complete-case cohort; the 5.5% excluded for missing predictors (mostly blood
  pressure) may differ systematically.
- Unweighted metrics; internal cross-validation on one survey cycle is not
  temporal or external validation.
- Self-reported diabetes and hypertension depend on prior diagnosis and access to
  care.
- The selection rule was written after an earlier version of this analysis had
  shown the untuned random forest slightly ahead of logistic regression. Nesting
  keeps the outer estimate honest for the rule as written, but the rule itself
  wasn't registered before any results existed.
