# Data lineage and provenance

This release is a read-only, aggregate analytics product. The lineage is:

```text
public release/API
  -> source-specific validation and quarantine
  -> dated manifest + raw/source checksum (when available)
  -> processed aggregate + sidecar checksum
  -> verified API repository
  -> typed dashboard response and rendered evidence page
```

The API never downloads source data at request time. It loads only the finite
allowlist in `api/repository.py`, verifies the artifact sidecar, verifies the
matching manifest, validates the JSON schema, and fails closed with a structured
integrity error when any boundary is stale or malformed.

## Source-to-artifact map

| Source | Population and grain | Validation boundary | Committed artifact | Evidence |
|---|---|---|---|---|
| CDC/NCHS NHANES 2017–2018 | MEC-examined U.S. civilian, noninstitutionalized adults; normalized participant record and survey-domain aggregate | Exact source manifest, release-specific files, participant-key and survey-design checks; both defining labs required for the primary indicator | `data/processed/patient_need_summary.json` and `patient_finding_model_comparison.json` | `public_observed` |
| AHRQ MEPS HC-243 2022 | Survey-eligible person-year records; source-specific utilization/expenditure aggregate | Fixed-width/native layout checks, variable contracts, survey weights, strata/PSU and missing-code preservation | `data/processed/meps_hc243_2022_landscape.json` | `public_observed` |
| CMS Medicare Part D 2024 | Provider, drug, and provider-reported geography aggregate for the explicit therapy dictionary | Complete pagination for selected generics, row/schema checks, provider identifiers removed from output | `data/processed/partd_2024_ckd_therapy_landscape.json` | `public_observed` |
| ClinicalTrials.gov API v2 | Registered study aggregate for the exact CKD condition query | Page-token reconciliation, stable total, valid identity count, duplicate/quarantine checks | `data/processed/clinicaltrials_ckd_landscape.json` | `public_observed` |
| CMS DE-SynPUF-compatible demonstration | Handcrafted schema-compatible claim events for a software method demonstration | Fixture manifest, exact fixture checksum, synthetic/fixture-only flags and no-cross-source-join check before read | `data/fixtures/synpuf_journeys.csv` | `public_synthetic` + `fixture_only` |

The NHANES raw XPT files are intentionally gitignored. Their URLs, byte counts,
and expected SHA-256 values are recorded in
`data/manifests/nhanes-2017-2018-patient-need.json`. CI does not fetch them.
The committed aggregate is the reproducible release boundary.

## Join and geography policy

NHANES, MEPS, Part D, and ClinicalTrials.gov are source-specific panels. There is
no patient-level cross-source join. NHANES and MEPS support national or survey-domain
interpretation; Part D retains provider-reported state; trials retain study-country
mentions. These are not one compatible geography and cannot form an observed state
leaderboard. The opportunity code accepts only explicitly compatible,
scenario-only inputs with shared time and compatibility keys.

## Provenance retained in the API

Every API evidence object retains source, release, population, grain, evidence type,
time window, limitations, artifact path, artifact SHA-256, and source-manifest path
when applicable. Null or unavailable values remain null/unknown; they are never
converted to zero. The dashboard repeats these boundaries on each page and the
synthetic page explicitly states that its data is not representative of Medicare
beneficiaries.
