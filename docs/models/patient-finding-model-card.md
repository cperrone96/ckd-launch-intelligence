# Patient-finding model card

All numbers below come from `data/processed/patient_finding_model_comparison.json`,
built by `python -m ckd_intelligence.analysis.nhanes_pipeline` (or notebook 02).

## Summary

The model ranks NHANES 2017-2018 adults by their probability of a cross-sectional
CKD laboratory indicator (eGFR <60 or UACR ≥30 mg/g) using only information that is
available before kidney labs are drawn. It estimates screening yield for a
population, not a diagnosis for a person.

Logistic regression was pre-specified as the reported model before any evaluation.
On pooled out-of-fold predictions it reaches ROC-AUC 0.772 (95% CI 0.759–0.784).
The clinical predictors add 0.031 ROC-AUC (0.018–0.045) over a demographics-only
model. A random forest is 0.008 ROC-AUC higher (0.003–0.014); logistic regression
remains the reported model because it was pre-specified, is well calibrated and
exports as a small, validated JSON scorer.

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

## Validation design

- Stratified grouped 5-fold cross-validation. The 30 NHANES masked variance PSUs
  (stratum × PSU) are the groups, so no PSU is in both a fitting and a scoring fold.
  Each fold scores 6 PSUs (919–979 people); every person receives one
  out-of-fold prediction.
- All models use the same folds. The no-skill reference is a constant score at the
  cohort prevalence.
- Uncertainty: 1,000 cluster-bootstrap replicates resample the 30 PSUs. Model
  differences are computed on the same replicates (paired). Fold models are held
  fixed, so intervals exclude refitting variability.
- Operating point: the top 10% of out-of-fold scores (474 of 4,741), ranked without
  labels; ties break by stable row order. The resulting score boundary (0.431) is
  the API's flag threshold for the final model, which is refit on all 4,741 people.
- An earlier version evaluated one untouched fold of 6 PSUs (993 people) with a
  demographics-only model. Re-running that model across the five folds of four
  random seeds gave single-fold ROC-AUCs from 0.73 to 0.76, and a 6-cluster
  bootstrap understates uncertainty, so pooled cross-validation replaced it.

## Performance (pooled out-of-fold, n = 4,741)

| Model | ROC-AUC (95% CI) | PR-AUC (95% CI) | Brier (95% CI) | Precision at top 10% | Recall at top 10% |
|---|---|---|---|---|---|
| Logistic regression, all predictors (reported) | 0.772 (0.759–0.784) | 0.464 (0.436–0.494) | 0.124 (0.118–0.131) | 0.557 (0.504–0.595) | 0.303 (0.280–0.320) |
| Random forest, all predictors | 0.780 (0.768–0.791) | 0.471 (0.442–0.502) | 0.123 (0.117–0.130) | 0.551 (0.515–0.589) | 0.300 (0.279–0.332) |
| Logistic regression, demographics only | 0.741 (0.725–0.756) | 0.412 (0.381–0.442) | 0.131 (0.124–0.138) | 0.511 (0.465–0.553) | 0.278 (0.257–0.302) |
| No-skill reference (constant prevalence) | 0.500 | 0.184 (0.170–0.196) | 0.150 (0.141–0.158) | not meaningful (tied scores) | not meaningful |

At the 10% operating point the logistic model flags people with the indicator at
3.0 times the base rate (precision 0.557 vs prevalence 0.184) and finds 30% of them
(264 true positives, 210 false positives, 606 false negatives).

### Paired differences (logistic regression minus comparator)

| Comparison | Estimate | 95% CI |
|---|---|---|
| vs demographics only, ROC-AUC | +0.031 | +0.018 to +0.045 |
| vs demographics only, PR-AUC | +0.052 | +0.024 to +0.082 |
| vs demographics only, Brier | −0.007 | −0.010 to −0.004 |
| vs random forest, ROC-AUC | −0.008 | −0.014 to −0.003 |
| vs random forest, PR-AUC | −0.007 | −0.014 to +0.001 |
| vs random forest, Brier | +0.001 | +0.000 to +0.002 |

### Calibration (logistic, out-of-fold quintiles)

| n | Mean predicted | Observed |
|---|---|---|
| 949 | 0.035 | 0.057 |
| 948 | 0.066 | 0.062 |
| 948 | 0.129 | 0.103 |
| 948 | 0.237 | 0.236 |
| 948 | 0.451 | 0.459 |

Predicted and observed rates agree closely in the upper three quintiles, where the
screening decisions are made.

### Subgroups at the 10% operating point

| Group | n | Positives | Prevalence | Precision | Recall |
|---|---|---|---|---|---|
| Age 18-39 | 1,552 | 107 | 0.069 | undefined (none flagged) | 0.000 |
| Age 40-59 | 1,453 | 186 | 0.128 | 0.500 | 0.070 |
| Age 60+ | 1,736 | 577 | 0.332 | 0.560 | 0.435 |
| Female | 2,423 | 442 | 0.182 | 0.534 | 0.287 |
| Male | 2,318 | 428 | 0.185 | 0.581 | 0.320 |

Age drives the ranking. A single 10% capacity selects no adult under 40, so the
107 indicator-positive young adults in the cohort are all missed. Serving that
group would need a separate threshold or a different screening policy.

### Indicator-definition sensitivity (same out-of-fold scores)

| Definition | Prevalence | ROC-AUC | PR-AUC |
|---|---|---|---|
| eGFR <60 or UACR ≥30 (primary) | 0.184 | 0.772 | 0.464 |
| eGFR <60 only | 0.081 | 0.848 | 0.310 |
| UACR ≥30 only | 0.133 | 0.724 | 0.334 |

Low eGFR is easier to rank from age and blood pressure than albuminuria is.

## Scoring artifact

The deployable scorer is strict JSON, not pickle: ordered features, category
levels, full-cohort scaling parameters, 19 coefficients and an intercept, with
explicit reject policies for missing, unknown and out-of-range inputs. The API's
`/api/v1/patient-finding/score` endpoint validates every field before scoring. A
test checks that the JSON scorer reproduces the fitted scikit-learn pipeline to
1e-12.

## Limitations

- Cross-sectional indicator, not chronic CKD; a single creatinine and spot UACR
  carry biological and measurement variability.
- Complete-case cohort; the 5.5% excluded for missing predictors (mostly blood
  pressure) may differ systematically.
- Unweighted metrics; internal cross-validation on one survey cycle is not
  temporal or external validation.
- Self-reported diabetes and hypertension depend on prior diagnosis and access to
  care.
