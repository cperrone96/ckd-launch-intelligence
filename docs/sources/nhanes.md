# NHANES ingestion contract

- Release: 2017–2018 public-use cycle
- Population: U.S. civilian, noninstitutionalized population represented by NHANES
- Grain: one normalized survey-participant record
- Evidence: public observed
- Coverage field: `survey_cycle`

Supported layouts are (1) the documented normalized UTF-8 exchange CSV, (2) a
participant-level pre-joined SAS XPORT export, and (3) a ZIP containing the native CDC
`DEMO_J.XPT`, `BIOPRO_J.XPT`, and `ALB_CR_J.XPT` components. The native bundle is
outer-joined one-to-one on `SEQN`; duplicate component keys fail closed. The resulting
contract requires `SEQN`, `RIDAGEYR`, `RIAGENDR`, `RIDRETH3`, `LBXSCR`, `URXUMA`,
`URXUCR`, `WTMEC2YR`, `SDMVSTRA`, and `SDMVPSU`. Native locators must name cycle
`2017-2018`; arbitrary XPT families are not claimed.

Input is capped at 300 MiB. The adapter preserves participant identifier, survey
cycle, sample weight, strata, PSU, documented sex/race codes, and laboratory units in
the normalized column names. Release/cycle identity, required fields, value ranges,
survey-design values, and participant-key uniqueness are validated before use.

Pandas supplies the XPORT decoder declared by the project runtime. Missing sentinels
are quarantined, never changed to zero. Downstream population
estimates must use the documented survey design and weights. Cross-sectional CKD
indicators are not confirmed clinical diagnoses.

## Patient-need snapshot

The patient-need notebook uses only the official 2017–2018 CDC/NCHS files listed in
`data/manifests/nhanes-2017-2018-patient-need.json`. Raw XPT files are cached under
`data/raw/nhanes/2017-2018/`, excluded from Git, and verified against the committed
SHA-256 values before any calculation. CI never downloads source data. When those
files are unavailable, the notebook uses a small committed representative fixture
and labels every output `fixture_only`; such output is not a population finding.

The population analysis is limited to records with `RIDSTATR=2` (MEC examined),
true positive 2-year MEC exam weights, and valid masked variance strata/PSUs. The SAS
pseudo-zero value used for missing weights is normalized to missing before filtering.
Adults are age 18 or older. Known pregnant participants (`RIDEXPRG=1`) are excluded
from the surveillance domain. `RIDEXPRG=2` (not pregnant), `3` (cannot ascertain),
and missing/not-applicable values (including males and age groups not asked) remain
eligible; this is therefore described as “excluding known pregnancy,” not as proof
that every retained participant was nonpregnant.

The primary cross-sectional indicator is eGFR <60 mL/min/1.73 m² OR UACR >=30 mg/g,
requiring both defining measures. eGFR uses the race-free 2021 CKD-EPI creatinine
equation. UACR uses the official NHANES `URDACT` albumin-creatinine ratio in mg/g,
documented in the official codebook URL committed with the source manifest. The
component-based fallback uses a tolerance-safe threshold comparison so values such
as urine albumin 10.2 mg/L and urine creatinine 34 mg/dL classify at exactly 30 mg/g.
Missing defining labs are unknown and excluded, never assigned zero or negative.

eGFR-only and albuminuria-only definitions are reported on the same primary
complete-case domain to isolate definition sensitivity rather than availability.
The headline and limitations qualify that complete-case inference may differ if
eligible adults with missing defining labs have different prevalence. Estimates use
2-year MEC weights, stratified-PSU Taylor linearization, Student-t confidence limits
with design degrees of freedom, and full-sample domain estimation. A lonely PSU is
an error rather than an implicit variance assumption.

Official public-observed and fixture-only outputs are written to separate paths.
Running the notebook without the raw CDC cache therefore cannot overwrite the
committed official aggregate. The root-runnable checksum names the full processed
artifact path.

## Analysis snapshot

The committed analysis reads eight 2017-2018 component files listed with SHA-256
digests in `data/manifests/nhanes-2017-2018-patient-need.json`: `DEMO_J`,
`BIOPRO_J`, `ALB_CR_J`, `BMX_J`, `BPX_J`, `DIQ_J`, `BPQ_J` and `SMQ_J`. Retrieve them
with `python scripts/retrieve_surveys.py`; `ckd_intelligence.cohorts.nhanes_2017_2018`
joins them one-to-one on `SEQN`.


## Predictor-ablation snapshot

The predictor-ablation analysis reads five more 2017-2018 files listed with SHA-256
digests in `data/manifests/nhanes-2017-2018-predictor-ablation.json`: `GHB_J`
(HbA1c), `CBC_J` (hemoglobin), `MCQ_J` (medical conditions), `HUQ_J` (health-care
use) and `RXQ_RX_J` (prescription medications). It also reads income-to-poverty
ratio and education from `DEMO_J`, waist circumference from `BMX_J` and diastolic
readings from `BPX_J`. `scripts/retrieve_surveys.py` downloads both manifests;
`ckd_intelligence.cohorts.nhanes_2017_2018_ablation` derives the predictors. The
deployed patient-finding model does not use any of them.

Refused and don't-know answers to clinical questions stay missing, as in the base
loader; people missing any ablation predictor leave the ablation cohort and are
counted in its attrition. The medical-history and education questions are asked only
of adults 20 and older, so the ablation cohort is in effect adults 20+. Income
nonresponse (about one in eight) is its own "Not reported" level. Diastolic pressure is the mean of readings above zero, because
NHANES records an inaudible diastolic as 0.

Prescription reason codes (`RXDRSC1`-`RXDRSC3`) are never read. Some name a kidney
diagnosis, which would leak the outcome; medication classes come from drug names only.
