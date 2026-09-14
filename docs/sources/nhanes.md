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
