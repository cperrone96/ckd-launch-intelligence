# Data dictionary

This dictionary describes the committed aggregate contracts. It does not describe
raw patient or provider rows because no such rows are committed.

## Common fields

| Field | Meaning | Rules |
|---|---|---|
| `source` | Source system or publisher | Kept with every evidence boundary |
| `release` / `source_release` | Source cycle, release, or API version | Never inferred from a different source |
| `evidence_type` | `public_observed`, `public_synthetic`, or `fixture_only` | Classification is validated; caller-created values cannot become observed |
| `grain` | Unit represented by the record or aggregate | Must be read with population and geography |
| `source_population` | Population represented by the source | Denominator and exclusions stay explicit |
| `limitations` | Non-empty list of interpretation constraints | Missing limitations fail artifact validation |
| `artifact` / `artifact_sha256` | Committed output and verified digest | The sidecar, manifest, and computed digest must agree |
| `source_manifest` | Upstream manifest for derived artifacts | Required for the NHANES patient-need and patient-finding artifacts |

Missingness is semantic. A missing value means unavailable or unknown; it is not a
zero. Person, beneficiary, provider, claim, and NCT identifiers are removed from
committed aggregate outputs and are not exposed by serialized API responses.

## Source-specific structures

| Artifact | Primary fields | Grain and interpretation |
|---|---|---|
| `patient_need_summary.json` | `estimates`, `waterfall`, `definition`, `survey_method`, `input_provenance` | NHANES survey-domain estimates. Each estimate includes point, confidence interval, denominator, design degrees of freedom, PSUs/strata, standard error, variance method, and source population. |
| `patient_finding_model_comparison.json` | `models`, `selected_model`, `selected_threshold`, `split`, `outcome`, `features`, `subgroups`, `paired_differences` | Held-out model-comparison aggregate. Metrics are unweighted and describe the analytic split, not population performance. No person-level scores are published. |
| `meps_hc243_2022_landscape.json` | `estimates`, `denominators`, `definition` | HC-243 consolidated person-year aggregate. `DSKIDN53` is a diabetes-related kidney-problem proxy and is not confirmed CKD. |
| `partd_2024_ckd_therapy_landscape.json` | `aggregates`, `dictionary`, `pagination`, `row_validation` | Provider/drug/provider-reported geography aggregate for selected generics. Absence of a provider-drug row is not zero; CMS suppresses providers with fewer than 11 total claims. |
| `clinicaltrials_ckd_landscape.json` | `status`, `phase_or_type`, `intervention`, `sponsor`, `geography`, `change_over_time`, `pagination` | Registered-study aggregate for the exact CKD query. Status and sponsor are registry metadata, not treatment effectiveness or patient demand. |
| `synpuf_journeys.csv` | `DESYNPUF_ID`, `CLM_ID`, claim type, service dates, diagnosis/provider codes, payment | Handcrafted schema-compatible synthetic demonstration. The identifiers are synthetic and remain inside the fixture-processing boundary. |

## API collection conventions

Collection endpoints return typed `items`, `pagination`, and `evidence`. Pagination
states whether a response is complete. A dashboard table showing a page window must
display the shown and total counts and say that the window is partial. Trial
dimensions retain their defining field: status uses `overall_status`, geography uses
`country`, sponsor uses `sponsor`, intervention uses `intervention`, update trends
use `update_year`, and phase/type uses its defining phase or study-type field.

The API intentionally exposes aggregate counts and metrics only. It does not return
beneficiary IDs, provider IDs, NCT IDs, raw claims, or raw NHANES participant keys.
